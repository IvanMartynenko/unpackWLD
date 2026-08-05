#include <windows.h>
#include <vector>
#include <map>
#include <iostream>
#include <fstream> // Added for file reading
#include <mmsystem.h>
#include <mfapi.h>
#include <mfplay.h>
#include <mfidl.h>
#pragma comment(lib, "winmm.lib")
#pragma comment(lib, "mfplat.lib")
#pragma comment(lib, "mfplay.lib")
#pragma comment(lib, "mfuuid.lib")
#pragma comment(lib, "ole32.lib")
#pragma comment(lib, "uuid.lib")
#pragma comment(lib, "gdi32.lib")


// =============================================================
// MEMORY UTILITIES
// =============================================================
namespace Mem {
    uintptr_t Base() {
        static uintptr_t base = (uintptr_t)GetModuleHandle(NULL);
        return base;
    }

    // Resolves the address of an IAT slot by walking the PE import table of the
    // main module, matching by DLL + function name. Unlike a hardcoded RVA, this
    // works across any build/patch of the EXE as long as the import itself is
    // still present under the same name.
    uintptr_t FindIATAddress(const char* dllName, const char* funcName) {
        uintptr_t base = Base();
        auto* dosHeader = (IMAGE_DOS_HEADER*)base;
        if (dosHeader->e_magic != IMAGE_DOS_SIGNATURE) return 0;

        auto* ntHeaders = (IMAGE_NT_HEADERS*)(base + dosHeader->e_lfanew);
        if (ntHeaders->Signature != IMAGE_NT_SIGNATURE) return 0;

        auto& importDir = ntHeaders->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT];
        if (importDir.VirtualAddress == 0) return 0;

        auto* importDesc = (IMAGE_IMPORT_DESCRIPTOR*)(base + importDir.VirtualAddress);
        for (; importDesc->Name != 0; importDesc++) {
            const char* currentDll = (const char*)(base + importDesc->Name);
            if (_stricmp(currentDll, dllName) != 0) continue;

            uintptr_t nameTableRVA = importDesc->OriginalFirstThunk ? importDesc->OriginalFirstThunk : importDesc->FirstThunk;
            auto* nameThunk = (IMAGE_THUNK_DATA*)(base + nameTableRVA);
            auto* iatThunk = (IMAGE_THUNK_DATA*)(base + importDesc->FirstThunk);

            for (; nameThunk->u1.AddressOfData != 0; nameThunk++, iatThunk++) {
                if (IMAGE_SNAP_BY_ORDINAL(nameThunk->u1.Ordinal)) continue;

                auto* importByName = (IMAGE_IMPORT_BY_NAME*)(base + nameThunk->u1.AddressOfData);
                if (strcmp((const char*)importByName->Name, funcName) == 0) {
                    return (uintptr_t)&iatThunk->u1.Function;
                }
            }
        }
        return 0;
    }

    // Locates a PE section by name (".text", ".rdata", ".data", ...) in the running
    // module and returns its in-memory range. Used to bound signature scans instead
    // of hardcoding section sizes, which differ between builds.
    bool GetSectionRange(const char* sectionName, uintptr_t* outStart, size_t* outSize) {
        uintptr_t base = Base();
        auto* dosHeader = (IMAGE_DOS_HEADER*)base;
        if (dosHeader->e_magic != IMAGE_DOS_SIGNATURE) return false;

        auto* ntHeaders = (IMAGE_NT_HEADERS*)(base + dosHeader->e_lfanew);
        if (ntHeaders->Signature != IMAGE_NT_SIGNATURE) return false;

        auto* section = IMAGE_FIRST_SECTION(ntHeaders);
        for (WORD i = 0; i < ntHeaders->FileHeader.NumberOfSections; i++, section++) {
            char name[9] = {};
            memcpy(name, section->Name, 8);
            if (_stricmp(name, sectionName) == 0) {
                *outStart = base + section->VirtualAddress;
                *outSize = section->Misc.VirtualSize;
                return true;
            }
        }
        return false;
    }

    // Parses an IDA-style byte pattern ("8B 45 ?? 89 45 ??") into byte/wildcard tokens.
    std::vector<int> ParsePattern(const char* pattern) {
        std::vector<int> tokens;
        const char* p = pattern;
        while (*p) {
            while (*p == ' ') p++;
            if (!*p) break;
            if (*p == '?') {
                tokens.push_back(-1);
                while (*p == '?') p++;
            }
            else {
                char* next = nullptr;
                tokens.push_back((int)strtol(p, &next, 16));
                p = next;
            }
        }
        return tokens;
    }

    // Scans [rangeStart, rangeStart + rangeSize) for the first occurrence of pattern.
    // Returns 0 if not found.
    uintptr_t FindPattern(const char* pattern, uintptr_t rangeStart, size_t rangeSize) {
        std::vector<int> tokens = ParsePattern(pattern);
        if (tokens.empty() || tokens.size() > rangeSize) return 0;

        const BYTE* data = (const BYTE*)rangeStart;
        size_t last = rangeSize - tokens.size();
        for (size_t i = 0; i <= last; i++) {
            bool match = true;
            for (size_t j = 0; j < tokens.size(); j++) {
                if (tokens[j] != -1 && data[i + j] != (BYTE)tokens[j]) {
                    match = false;
                    break;
                }
            }
            if (match) return rangeStart + i;
        }
        return 0;
    }

    // Convenience overload: scans a whole named section of the running module.
    uintptr_t FindPattern(const char* pattern, const char* sectionName = ".text") {
        uintptr_t start = 0;
        size_t size = 0;
        if (!GetSectionRange(sectionName, &start, &size)) return 0;
        return FindPattern(pattern, start, size);
    }

    // Like FindPattern, but returns every match. Used for "patch every literal
    // reference to this address" sites, where the compiler may emit a different
    // number of copies of the same immediate across builds (CSE, register reuse, ...).
    std::vector<uintptr_t> FindAllPatterns(const char* pattern, const char* sectionName = ".text") {
        std::vector<uintptr_t> results;
        uintptr_t start = 0;
        size_t size = 0;
        if (!GetSectionRange(sectionName, &start, &size)) return results;

        std::vector<int> tokens = ParsePattern(pattern);
        if (tokens.empty() || tokens.size() > size) return results;

        const BYTE* data = (const BYTE*)start;
        size_t last = size - tokens.size();
        for (size_t i = 0; i <= last; i++) {
            bool match = true;
            for (size_t j = 0; j < tokens.size(); j++) {
                if (tokens[j] != -1 && data[i + j] != (BYTE)tokens[j]) {
                    match = false;
                    break;
                }
            }
            if (match) results.push_back(start + i);
        }
        return results;
    }

    // Finds every "call rel32" (E8) instruction in a section whose computed
    // destination equals targetAddr. Used to locate a call site once the callee's
    // address is already known (e.g. from its own entry signature), instead of
    // hardcoding the caller's address directly.
    std::vector<uintptr_t> FindCallers(uintptr_t targetAddr, const char* sectionName = ".text") {
        std::vector<uintptr_t> results;
        uintptr_t start = 0;
        size_t size = 0;
        if (!GetSectionRange(sectionName, &start, &size) || size < 5) return results;

        const BYTE* data = (const BYTE*)start;
        for (size_t i = 0; i + 5 <= size; i++) {
            if (data[i] == 0xE8) {
                int32_t rel;
                memcpy(&rel, data + i + 1, 4);
                uintptr_t dest = (start + i + 5) + (uintptr_t)(intptr_t)rel;
                if (dest == targetAddr) results.push_back(start + i);
            }
        }
        return results;
    }

    template <typename T>
    void Write(uintptr_t address, T value) {
        DWORD oldProtect;
        VirtualProtect((void*)address, sizeof(T), PAGE_EXECUTE_READWRITE, &oldProtect);
        *(T*)address = value;
        VirtualProtect((void*)address, sizeof(T), oldProtect, &oldProtect);
    }

    void WriteBytes(uintptr_t address, const void* data, size_t size) {
        DWORD oldProtect;
        VirtualProtect((void*)address, size, PAGE_EXECUTE_READWRITE, &oldProtect);
        memcpy((void*)address, data, size);
        VirtualProtect((void*)address, size, oldProtect, &oldProtect);
    }

    void MakeJMP(uintptr_t from, uintptr_t to, int nopCount = 0) {
        DWORD oldProtect;
        size_t size = 5 + nopCount;
        VirtualProtect((void*)from, size, PAGE_EXECUTE_READWRITE, &oldProtect);
        uintptr_t relative = to - from - 5;
        *(BYTE*)from = 0xE9;
        *(DWORD*)(from + 1) = relative;
        if (nopCount > 0) {
            memset((void*)(from + 5), 0x90, nopCount);
        }
        VirtualProtect((void*)from, size, oldProtect, &oldProtect);
    }

    // New: Patch IAT (Import Address Table)
    void PatchIAT(uintptr_t iatAddress, uintptr_t hookFunction, uintptr_t* storageOriginal) {
        if (iatAddress == 0) return;

        DWORD oldProtect;
        VirtualProtect((void*)iatAddress, 4, PAGE_EXECUTE_READWRITE, &oldProtect);

        // Save the original function address
        if (storageOriginal && *storageOriginal == 0) {
            *storageOriginal = *(uintptr_t*)iatAddress;
        }

        // Write our hook address
        *(uintptr_t*)iatAddress = hookFunction;
        VirtualProtect((void*)iatAddress, 4, oldProtect, &oldProtect);
    }
}

// =============================================================
// GLOBAL DATA & SETTINGS
// =============================================================
namespace ModContext {
    int ChapterReqs[] = { 2, 4, 4, 1, 3, 1, 1, 1, 1 };
    int MissionCount = 18;

    // Config toggles
    bool EnableConsole = false;
    bool EnableLog = false;
    bool EditorMode = false;
    bool WindowedMode = false;
    bool NoCd = false;
    bool EnableMusicHook = false;

    // Special Mission Configuration (with default game values)
    int SpecialMission1 = 11;
    int SpecialMission2 = 17;
    int SpecialMission3 = 16;
    int BarracksID = 15;
    int ConcernID = 18;

    std::vector<int> NewMissionsArray;
    std::map<int, int> MissionRemapMap;

    // Missons handle to identify our custom resources
    const int MISSIONS_IMAGE_HANDLE_START = 10000;

    std::string GameFile = "VaBank.wld";
    std::string DialogFile = "data\\dialogs_rus.txt";

    // String text storage (to keep them in memory)
    std::vector<std::string> TaxiNames;
    // Array of pointers that we will feed to the game
    // The game expects const char* (or 0 for a separator)
    std::vector<const char*> TaxiPtrArray;
}

namespace FileLoading {
    // Stores raw file data for files loaded from disk. 
    std::map<int, std::vector<uint8_t>> FileCache;
    // =============================================================
    // ORIGINAL API POINTERS (For IAT Hooking)
    // =============================================================
    typedef HRSRC(WINAPI* FindResourceA_t)(HMODULE, LPCSTR, LPCSTR);
    typedef HGLOBAL(WINAPI* LoadResource_t)(HMODULE, HRSRC);
    typedef LPVOID(WINAPI* LockResource_t)(HGLOBAL);
    typedef HANDLE(WINAPI* LoadImageA_t)(HINSTANCE, LPCSTR, UINT, int, int, UINT);

    FindResourceA_t Original_FindResourceA = nullptr;
    LoadResource_t  Original_LoadResourceA = nullptr;
    LockResource_t  Original_LockResource = nullptr;
    LoadImageA_t    Original_LoadImageA = nullptr;

    // =============================================================
    // FILE LOADING LOGIC
    // =============================================================

    // Helper to check if a file exists on disk
    bool FileExists(const char* filename) {
        struct stat buffer;
        return (stat(filename, &buffer) == 0);
    }

    // Returns true if a custom file was loaded, false otherwise
    bool LoadCustomFile(int resourceID) {
        // 1. If already cached, return true immediately
        if (FileCache.count(resourceID)) return true;

        std::string filePath = "";
        char tempPath[128];

        // =========================================================
        // CASE 1: Custom Missions (ID > ModContext::MISSIONS_IMAGE_HANDLE_START)
        // =========================================================
        if (resourceID > ModContext::MISSIONS_IMAGE_HANDLE_START) {
            // Example: ID 10001 -> mods\missions\1.tif
            int fileIndex = resourceID - ModContext::MISSIONS_IMAGE_HANDLE_START;
            sprintf_s(tempPath, "mods\\missions\\%d.tif", fileIndex);

            // We assume for >ModContext::MISSIONS_IMAGE_HANDLE_START we *must* load it, or it will fail later.
            // But we check existence to be safe.
            if (FileExists(tempPath)) {
                filePath = tempPath;
            }
        }
        // =========================================================
        // CASE 2: Original Replacements (ID < ModContext::MISSIONS_IMAGE_HANDLE_START)
        // =========================================================
        else {
            // Priority 1: mods\images\%d.tif
            sprintf_s(tempPath, "mods\\images\\%d.tif", resourceID);
            if (FileExists(tempPath)) {
                filePath = tempPath;
            }
            else {
                // Priority 2: mods\images\%d.bmp
                sprintf_s(tempPath, "mods\\images\\%d.bmp", resourceID);
                if (FileExists(tempPath)) {
                    filePath = tempPath;
                }
                else {
                    // Priority 3: mods\interfaces\%d.nmf
                    sprintf_s(tempPath, "mods\\interfaces\\%d.nmf", resourceID);
                    if (FileExists(tempPath)) {
                        filePath = tempPath;
                    }
                }
            }
        }

        // If no custom file was found, return false (let the game handle it)
        if (filePath.empty()) return false;

        // Load the file into memory
        std::ifstream file(filePath, std::ios::binary | std::ios::ate);
        if (file.is_open()) {
            size_t size = file.tellg();
            file.seekg(0, std::ios::beg);

            std::vector<uint8_t>& buffer = FileCache[resourceID];
            buffer.resize(size);
            file.read((char*)buffer.data(), size);

            // printf("[System] Loaded custom resource: %s\n", filePath.c_str());
            return true;
        }

        return false;
    }

    // =============================================================
    // HOOK FUNCTIONS (IAT)
    // =============================================================

    HRSRC WINAPI Hook_FindResourceA(HMODULE hModule, LPCSTR lpName, LPCSTR lpType) {
        // Check if lpName is an Integer ID
        if (IS_INTRESOURCE(lpName)) {
            int id = (int)lpName;

            // Try to load a custom file based on the new logic
            if (LoadCustomFile(id)) {
                // If loaded successfully (either > ModContext::MISSIONS_IMAGE_HANDLE_START or < ModContext::MISSIONS_IMAGE_HANDLE_START replacement),
                // return the ID as the handle.
                return (HRSRC)id;
            }
        }

        // If no custom file found, run original game logic
        return Original_FindResourceA(hModule, lpName, lpType);
    }

    HGLOBAL WINAPI Hook_LoadResource(HMODULE hModule, HRSRC hResInfo) {
        int id = (int)hResInfo;

        // Check if this ID exists in our cache
        if (FileCache.count(id)) {
            // Return pointer to the data inside the vector
            return (HGLOBAL)FileCache[id].data();
        }

        // Otherwise, use original function
        return Original_LoadResourceA(hModule, hResInfo);
    }

    LPVOID WINAPI Hook_LockResource(HGLOBAL hResData) {
        // For our custom data, LoadResource already returned the raw pointer.
        // However, we should check if this pointer belongs to our cache.

        // Simple optimization: If the pointer points into our heap, just return it.
        // Since we returned the .data() pointer in LoadResource, we just return it here.
        // The game treats the HGLOBAL as a pointer in standard implementation mostly anyway.

        return (LPVOID)hResData;

        // Note: If the game crashes here, we might need to verify if hResData
        // is actually one of our pointers, but usually passing it through is safe
        // if the original LockResource handles unknown pointers gracefully (or we filter).
        // But logically, if we returned the pointer in LoadResource, the game passes it here.
    }

    // A subset of bitmaps (e.g. resource 545/0x221 and others) is loaded by the game
    // through LoadImageA(hInstance, id, IMAGE_BITMAP, ...) instead of the
    // FindResourceA/LoadResource/LockResource triplet. LoadImageA resolves the resource
    // internally inside USER32.DLL, so it never touches this EXE's own FindResourceA
    // import and the hooks above never see it. It needs its own IAT hook.
    HANDLE WINAPI Hook_LoadImageA(HINSTANCE hInst, LPCSTR lpszName, UINT uType, int cxDesired, int cyDesired, UINT fuLoad) {
        if (uType == IMAGE_BITMAP && IS_INTRESOURCE(lpszName)) {
            int id = (int)(intptr_t)lpszName;
            char tempPath[128];
            sprintf_s(tempPath, "mods\\images\\%d.bmp", id);

            if (FileExists(tempPath)) {
                // Load directly from disk, bypassing the resource system entirely.
                HANDLE hBitmap = Original_LoadImageA(NULL, tempPath, IMAGE_BITMAP, cxDesired, cyDesired, fuLoad | LR_LOADFROMFILE);
                if (hBitmap) return hBitmap;
            }
        }

        // If no custom file found, run original game logic
        return Original_LoadImageA(hInst, lpszName, uType, cxDesired, cyDesired, fuLoad);
    }

    void Hook() {
        Mem::PatchIAT(Mem::FindIATAddress("KERNEL32.dll", "FindResourceA"), (uintptr_t)Hook_FindResourceA, (uintptr_t*)&Original_FindResourceA);
        Mem::PatchIAT(Mem::FindIATAddress("KERNEL32.dll", "LoadResource"), (uintptr_t)Hook_LoadResource, (uintptr_t*)&Original_LoadResourceA);
        Mem::PatchIAT(Mem::FindIATAddress("KERNEL32.dll", "LockResource"), (uintptr_t)Hook_LockResource, (uintptr_t*)&Original_LockResource);
        Mem::PatchIAT(Mem::FindIATAddress("USER32.dll", "LoadImageA"), (uintptr_t)Hook_LoadImageA, (uintptr_t*)&Original_LoadImageA);
    }
}

// Hook() here is never called (see the commented-out call in Init()) - left on
// hardcoded VaBank.exe addresses rather than converted to signature scanning,
// since there is currently nothing that would run this code on any build. If this
// gets re-enabled, it needs the same treatment as the rest of this file first.
namespace RemapMissionInMenu {
    const int GAME_OFFSET_CONST = 0xD;

    extern "C" void __stdcall RemapMissions(uintptr_t ebxValue) {
        if (ebxValue != 0x0057C124) return;

        uintptr_t ptrStorage = ebxValue + 0x2C;
        const char* description = *(const char**)ptrStorage;

        if (description != nullptr && !IsBadReadPtr(description, 1)) {
            if (strstr(description, "........") != nullptr) return;
        }

        DWORD* valuePtr = (DWORD*)(ebxValue + 0x70);
        DWORD rawValue = *valuePtr;
        int logicValue = (int)rawValue - GAME_OFFSET_CONST;

        if (ModContext::MissionRemapMap.count(logicValue)) {
            int newLogicValue = ModContext::MissionRemapMap[logicValue];
            *valuePtr = newLogicValue + GAME_OFFSET_CONST;
        }
    }

    DWORD RetAddr_FixEBX = 0x0046C7A9;
    __declspec(naked) void Hook_FixEBXValues() {
        __asm {
            pushad
            pushfd
            push ebx
            call RemapMissions
            popfd
            popad
            mov ecx, dword ptr[ebx + 0x70]
            mov edi, dword ptr[ebx + 0x64]
            jmp RetAddr_FixEBX
        }
    }

    void Hook() {
        Mem::MakeJMP(0x0046C7A3, (uintptr_t)Hook_FixEBXValues, 1);
    }
}

namespace CreateMissionImages {
    // UI Object Array
    std::vector<int> MissionImagesArray;

    // Function Pointers for InitMissionImages - resolved at runtime in Hook(),
    // see FindAnchors() below.
    typedef void(__thiscall* tModelConstructor)(void* thisPtr, int arg1);
    tModelConstructor Call_ModelConstructor = nullptr;

    typedef void(__cdecl* tModelSetup)(void* resourcePtr, void* instancePtr);
    tModelSetup Call_ModelSetup = nullptr;

    typedef uintptr_t(__cdecl* tCreateUIObject)(int id, const char* name, int arg3);
    tCreateUIObject Call_CreateUIObject = nullptr;

    uintptr_t* Game_Ptr_Context = nullptr;

    // Original locations of the four MissionImagesArray literal references (two
    // "-4"-adjusted). Resolved in Hook(), used every time InitMissionImages() runs.
    uintptr_t ArrayRefSiteMain1 = 0;
    uintptr_t ArrayRefSiteMain2 = 0;
    uintptr_t ArrayRefSiteMinus4_1 = 0;
    uintptr_t ArrayRefSiteMinus4_2 = 0;

    // =============================================================
    // MAIN LOGIC: INIT IMAGES (MODIFIED)
    // =============================================================
    extern "C" void __stdcall InitMissionImages() {
        MissionImagesArray.resize(ModContext::MissionCount + 1);

        std::cout << "[SYSTEM] Generating " << ModContext::MissionCount << " mission icons..." << std::endl;

        for (int i = 0; i <= ModContext::MissionCount; i++) {

            // === LOGIC CHANGE HERE ===
            // We use ID = ModContext::MISSIONS_IMAGE_HANDLE_START + i + 1. 
            // This creates a unique ID > ModContext::MISSIONS_IMAGE_HANDLE_START which our Hook_FindResourceA detects.
            int customResourceID = ModContext::MISSIONS_IMAGE_HANDLE_START + i + 1;

            // Create the UI Container with the custom ID
            uintptr_t parentObject = Call_CreateUIObject(customResourceID, "foto_hotel", 0);

            if (parentObject == 0) {
                std::cout << "[ERROR] Failed to create mission for ID: " << i + 1 << ". Image for mission not found." << std::endl;
                continue;
            }

            // Manually trigger resource loading
            // Because we installed IAT Hooks, this call goes to Hook_FindResourceA
            HRSRC hRes = FindResourceA(GetModuleHandle(NULL), MAKEINTRESOURCEA(customResourceID), "MODELS");

            if (!hRes) {
                // Fallback: If custom file not found, try default 0x1CC
                hRes = FindResourceA(GetModuleHandle(NULL), MAKEINTRESOURCEA(0x1CC), "MODELS");
            }

            if (!hRes) continue; // Should not happen if default exists

            // Hook_LoadResource intercepts this if hRes is our custom ID
            HGLOBAL hData = LoadResource(GetModuleHandle(NULL), hRes);
            void* pResourceData = LockResource(hData);

            // Standard Game Setup
            *Game_Ptr_Context = parentObject;
            void* newObject = malloc(0x154);

            if (newObject) {
                memset(newObject, 0, 0x154);
                Call_ModelConstructor(newObject, 0);
                Call_ModelSetup(pResourceData, newObject);
                MissionImagesArray[i] = (int)newObject;
            }
        }

        // Apply Patches for the Image Array pointer
        uintptr_t newArrayAddress = (uintptr_t)MissionImagesArray.data();
        Mem::Write<uintptr_t>(ArrayRefSiteMinus4_1, newArrayAddress - 4);
        Mem::Write<uintptr_t>(ArrayRefSiteMain1, newArrayAddress);
        Mem::Write<uintptr_t>(ArrayRefSiteMain2, newArrayAddress);
        Mem::Write<uintptr_t>(ArrayRefSiteMinus4_2, newArrayAddress - 4);

        std::cout << "[SYSTEM] Icons Initialized." << std::endl;
    }

    // Image Setup Hook - resolved at runtime, see FindAnchors() below.
    DWORD RetAddr_ImageInit = 0;
    DWORD Func_OriginalCall = 0;

    __declspec(naked) void Hook_SetupImages() {
        __asm {
            pushad
            pushfd
            call InitMissionImages
            popfd
            popad
            call Func_OriginalCall
            jmp RetAddr_ImageInit
        }
    }

    struct Anchors {
        uintptr_t modelConstructor;
        uintptr_t modelSetup;
        uintptr_t createUIObject;
        uintptr_t gamePtrContext;
        uintptr_t arrayMain1;
        uintptr_t arrayMain2;
        uintptr_t arrayMinus4_1;
        uintptr_t arrayMinus4_2;
        uintptr_t originalSetupFunc;
        uintptr_t hookSite;
        bool AllFound() const {
            return modelConstructor && modelSetup && createUIObject && gamePtrContext
                && arrayMain1 && arrayMain2 && arrayMinus4_1 && arrayMinus4_2
                && originalSetupFunc && hookSite;
        }
    };

    // Disambiguates the two near-identical "load resource by type, SEH-prologue"
    // function entries (one for MODELS, one for IMAGES - same shape, different
    // resource-type string) by checking the actual string content, not just the
    // instruction shape which is identical between them.
    uintptr_t FindResourceLoaderEntry(const char* wantedType) {
        std::vector<uintptr_t> candidates = Mem::FindAllPatterns(
            "64 A1 00 00 00 00 6A FF 68 ?? ?? ?? ?? 50 64 89 25 00 00 00 00 56 57 "
            "E8 ?? ?? ?? ?? 8B 70 08 E8 ?? ?? ?? ?? 8B 78 08 8B 44 24 ?? 25 FF FF 00 00 68 ?? ?? ?? ??",
            ".text");
        for (uintptr_t entry : candidates) {
            uintptr_t strPtr = *(uintptr_t*)(entry + 49);
            if (strPtr != 0 && strcmp((const char*)strPtr, wantedType) == 0) {
                return entry;
            }
        }
        return 0;
    }

    Anchors FindAnchors() {
        Anchors a{};
        a.modelConstructor = Mem::FindPattern(
            "6A FF 68 ?? ?? ?? ?? 64 A1 00 00 00 00 50 64 89 25 00 00 00 00 81 EC 04 02 00 00 53 55 56", ".text");
        a.modelSetup = Mem::FindPattern(
            "6A FF 68 ?? ?? ?? ?? 64 A1 00 00 00 00 50 64 89 25 00 00 00 00 83 EC 24 53 8B 5C 24 38 55 56 57 33 F6 6A 64", ".text");
        a.createUIObject = Mem::FindPattern(
            "64 A1 00 00 00 00 6A FF 68 ?? ?? ?? ?? 50 64 89 25 00 00 00 00 81 EC ?? ?? 00 00 56 57 E8 ?? ?? ?? ?? 8B 70 08 E8 ?? ?? ?? ?? 8B 78 08", ".text");

        uintptr_t gpcAnchor = Mem::FindPattern("8D 4C 24 ?? 89 2D ?? ?? ?? ??", ".text");
        if (gpcAnchor != 0) a.gamePtrContext = *(uintptr_t*)(gpcAnchor + 6);

        // MissionImagesArray literal references (see PatchAllLiteralRefs-style
        // reasoning in Missions::Hook - each of these four sites is individually
        // anchored rather than found via "patch every literal occurrence", because
        // (unlike ChapterReqs/NewMissionsArray) this address turned out to collide
        // with ~150 unrelated references elsewhere in the binary).
        uintptr_t site;
        site = Mem::FindPattern("8B 04 BD ?? ?? ?? ??", ".text");
        if (site != 0) a.arrayMain1 = site + 3;
        site = Mem::FindPattern("8B 86 ?? ?? ?? ?? 8B 4E 48 8B 14 BD ?? ?? ?? ??", ".text");
        if (site != 0) a.arrayMain2 = site + 12;
        site = Mem::FindPattern("A1 ?? ?? ?? ?? 8B 74 24 ?? 6A 01 33 DB 8B 0C 85 ?? ?? ?? ??", ".text");
        if (site != 0) a.arrayMinus4_1 = site + 16;
        site = Mem::FindPattern("E8 ?? ?? ?? ?? 50 A1 ?? ?? ?? ?? 8B 0C 85 ?? ?? ?? ??", ".text");
        if (site != 0) a.arrayMinus4_2 = site + 14;

        // The "setup mission images" hook site: find the MODELS-type resource
        // loader by content, then find whichever of its (many) callers is
        // immediately preceded by a write to Game_Ptr_Context - that's the one
        // driving mission icon creation specifically, not the ~20 other unrelated
        // model-loading call sites that share the same callee.
        a.originalSetupFunc = FindResourceLoaderEntry("MODELS");
        if (a.originalSetupFunc != 0 && a.gamePtrContext != 0) {
            BYTE needle[6] = { 0x89, 0x0D, 0, 0, 0, 0 };
            memcpy(needle + 2, &a.gamePtrContext, 4);
            for (uintptr_t caller : Mem::FindCallers(a.originalSetupFunc, ".text")) {
                BYTE prev[6];
                memcpy(prev, (void*)(caller - 6), 6);
                if (memcmp(prev, needle, 6) == 0) {
                    a.hookSite = caller;
                    break;
                }
            }
        }

        return a;
    }

    void Hook() {
        Anchors a = FindAnchors();
        if (!a.AllFound()) {
            if (ModContext::EnableConsole) std::cout << "[PATCH] CreateMissionImages: one or more anchors not found on this build, skipping." << std::endl;
            return;
        }

        Call_ModelConstructor = (tModelConstructor)a.modelConstructor;
        Call_ModelSetup = (tModelSetup)a.modelSetup;
        Call_CreateUIObject = (tCreateUIObject)a.createUIObject;
        Game_Ptr_Context = (uintptr_t*)a.gamePtrContext;
        ArrayRefSiteMain1 = a.arrayMain1;
        ArrayRefSiteMain2 = a.arrayMain2;
        ArrayRefSiteMinus4_1 = a.arrayMinus4_1;
        ArrayRefSiteMinus4_2 = a.arrayMinus4_2;
        Func_OriginalCall = (DWORD)a.originalSetupFunc;
        RetAddr_ImageInit = (DWORD)(a.hookSite + 5);

        Mem::MakeJMP(a.hookSite, (uintptr_t)Hook_SetupImages, 0);
    }
}

namespace ChapterReqs {
    // Locates the default requirements array {2,4,4,1,3,1,1,1,1} by content rather
    // than a fixed address. No direct instruction in .text embeds this address as a
    // literal (it's evidently reached through a computed/indirect pointer), so a
    // static disassembly xref isn't available - but the byte sequence itself is
    // confirmed unique in the whole image on every build checked so far.
    const char* DEFAULT_PATTERN =
        "02 00 00 00 04 00 00 00 04 00 00 00 01 00 00 00 "
        "03 00 00 00 01 00 00 00 01 00 00 00 01 00 00 00 01 00 00 00";

    // Exposed so Missions::Hook() can locate the (adjacent, in the original layout)
    // default mission-levels array relative to this one, instead of re-deriving it.
    uintptr_t ArrayAddr = 0;

    void Hook() {
        ArrayAddr = Mem::FindPattern(DEFAULT_PATTERN, ".data");
        if (ArrayAddr == 0) {
            if (ModContext::EnableConsole) std::cout << "[PATCH] ChapterReqs pattern not found, skipping." << std::endl;
            return;
        }

        for (int i = 0; i < 9; i++) {
            Mem::Write<int>(ArrayAddr + (i * 4), ModContext::ChapterReqs[i]);
        }
    }
}

namespace Missions {
    // Boolean Status Array
    uintptr_t PtrMissionCompletelyArray = 0;

    // Game Pointers
    unsigned char* RawBuffer = nullptr;
    uintptr_t PtrMissionNameArray = 0;
    uintptr_t PtrMissionInfoArray = 0;

    // Settings
    const int ELEMENT_SIZE = 8;
    int LoopLimit = 0;
    // =============================================================
    // NAKED HOOKS
    // Return addresses are resolved at runtime in Hook() (see anchors below)
    // instead of hardcoded - the naked functions just read whatever value is
    // in these globals at call time, which is always after Hook() has run.
    // =============================================================
    DWORD RetAddr_Init1 = 0;
    __declspec(naked) void Hook_InitArray1() {
        __asm {
            push ModContext::MissionCount
            mov ecx, PtrMissionNameArray
            push 0x8
            push ecx
            jmp RetAddr_Init1
        }
    }
    DWORD RetAddr_Init2 = 0;
    __declspec(naked) void Hook_InitArray2() {
        __asm {
            push ModContext::MissionCount
            mov edx, PtrMissionInfoArray
            push 0x8
            push edx
            jmp RetAddr_Init2
        }
    }
    DWORD RetAddr_MenuTitle = 0;
    __declspec(naked) void Hook_Menu_GetTitle() {
        __asm {
            mov edx, PtrMissionNameArray
            lea edx, [edx + eax * 8]
            jmp RetAddr_MenuTitle
        }
    }
    DWORD RetAddr_MenuDesc = 0;
    __declspec(naked) void Hook_Menu_GetDesc() {
        __asm {
            mov eax, PtrMissionInfoArray
            lea eax, [eax + edx * 8]
            jmp RetAddr_MenuDesc
        }
    }

    // Overwrites every literal occurrence of a 4-byte address in .text with a new
    // one. Used for sites whose original target isn't independently anchored, where
    // the compiler may re-embed the same literal a different number of times across
    // builds (CSE/register reuse) - safer to patch "however many there are" than to
    // assume a fixed count.
    void PatchAllLiteralRefs(uintptr_t oldAddr, uintptr_t newAddr) {
        char pattern[16];
        sprintf_s(pattern, "%02X %02X %02X %02X",
            (unsigned)(oldAddr & 0xFF), (unsigned)((oldAddr >> 8) & 0xFF),
            (unsigned)((oldAddr >> 16) & 0xFF), (unsigned)((oldAddr >> 24) & 0xFF));
        for (uintptr_t hit : Mem::FindAllPatterns(pattern, ".text")) {
            Mem::Write<uintptr_t>(hit, newAddr);
        }
    }

    // The mission-completion bool array (9 direct references + 2 "address-1"
    // references, confirmed by exhaustive literal search on both builds checked -
    // no other value collides). Its original address isn't near any other anchor
    // we already have, so it needs its own: "mov reg,reg / xor eax,eax / mov
    // reg,<addr>" happens to occur twice pointing at the same address; either
    // occurrence is enough to read it off.
    void PatchBoolArrayReferences() {
        uintptr_t anchor = Mem::FindPattern("8B D1 33 C0 BF ?? ?? ?? ??", ".text");
        if (anchor == 0) {
            if (ModContext::EnableConsole) std::cout << "[PATCH] Mission-completion array anchor not found, skipping." << std::endl;
            return;
        }
        uintptr_t originalAddr = *(uintptr_t*)(anchor + 5);

        uintptr_t newAddr = PtrMissionCompletelyArray;
        PatchAllLiteralRefs(originalAddr, newAddr);
        PatchAllLiteralRefs(originalAddr - 1, newAddr - 1);
    }

    // All of the anchors this Hook() depends on. Resolved up front so the whole
    // feature can be applied atomically - if any one anchor is missing on a given
    // build, none of the interdependent patches below are applied (a half-patched
    // state, e.g. menu getters pointing at our buffer while the init code still
    // targets the game's own array, would be worse than not patching at all).
    struct Anchors {
        uintptr_t init;       // array-allocation function
        uintptr_t loopA;      // mission-count global + EBP patch
        uintptr_t loopB;      // negative-offset patch (starts at same addr as loopA+17)
        uintptr_t loopC;      // loop-limit patch
        uintptr_t menuTitle;
        uintptr_t menuDesc;
        bool AllFound() const { return init && loopA && loopB && loopC && menuTitle && menuDesc; }
    };

    Anchors FindAnchors() {
        Anchors a{};
        a.init = Mem::FindPattern(
            "89 AE ?? ?? ?? ?? 89 AE ?? ?? ?? ?? 89 BE ?? ?? ?? ?? 89 BE ?? ?? ?? ??", ".text");
        a.loopA = Mem::FindPattern(
            "39 1D ?? ?? ?? ?? 0F 8E ?? ?? ?? ?? BF 01 00 00 00 8D AE ?? ?? ?? ??", ".text");
        a.loopB = Mem::FindPattern(
            "8D AE ?? ?? ?? ?? 8D 4C 24 ?? E8 ?? ?? ?? ?? 57 8D 44 24 ?? 68 ?? ?? ?? ?? 50 "
            "C6 84 24 ?? ?? ?? ?? ?? E8 ?? ?? ?? ?? 83 C4 0C 8D 4C 24 ?? E8 ?? ?? ?? ?? 50 "
            "B9 ?? ?? ?? ?? E8 ?? ?? ?? ?? 50 8D 8D ?? ?? ?? ??", ".text");
        a.loopC = Mem::FindPattern("A1 ?? ?? ?? ?? 83 C5 08 47 8D 57 FF 3B D0", ".text");
        a.menuTitle = Mem::FindPattern(
            "8B 4C 24 ?? 8B 01 83 F8 FF 0F 84 ?? ?? ?? ?? 8D 94 C6 ?? ?? ?? ??", ".text");
        a.menuDesc = Mem::FindPattern(
            "83 C4 18 8B 11 8D 8C 24 ?? ?? ?? ?? 8D 84 D6 ?? ?? ?? ??", ".text");
        return a;
    }

    void Hook() {
        size_t arraySize = ModContext::MissionCount * ELEMENT_SIZE;
        size_t boolSize = ModContext::MissionCount * sizeof(bool);
        size_t totalSize = (arraySize * 2) + boolSize + 1024;

        RawBuffer = (unsigned char*)VirtualAlloc(NULL, totalSize, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
        if (!RawBuffer) {
            if (ModContext::EnableConsole) std::cout << "[ERROR] Missions::Hook VirtualAlloc failed, skipping." << std::endl;
            return;
        }
        PtrMissionNameArray = (uintptr_t)RawBuffer;
        PtrMissionInfoArray = (uintptr_t)(RawBuffer + arraySize);
        PtrMissionCompletelyArray = (uintptr_t)(RawBuffer + (arraySize * 2));

        uintptr_t ptrNewData = (uintptr_t)ModContext::NewMissionsArray.data();

        Anchors a = FindAnchors();
        if (!a.AllFound()) {
            if (ModContext::EnableConsole) {
                std::cout << "[PATCH] Missions: one or more anchors not found on this build "
                    "(init=" << (a.init != 0) << " loopA=" << (a.loopA != 0)
                    << " loopB=" << (a.loopB != 0) << " loopC=" << (a.loopC != 0)
                    << " menuTitle=" << (a.menuTitle != 0) << " menuDesc=" << (a.menuDesc != 0)
                    << "), skipping all Missions hooks." << std::endl;
            }
            return;
        }

        // Arrays Init
        RetAddr_Init1 = (DWORD)(a.init + 45);
        RetAddr_Init2 = (DWORD)(a.init + 77);
        Mem::MakeJMP(a.init + 34, (uintptr_t)Hook_InitArray1, 6);
        Mem::MakeJMP(a.init + 66, (uintptr_t)Hook_InitArray2, 6);

        // Mission-count global (also used by the loop-limit patch below)
        uintptr_t missionCountAddr = *(uintptr_t*)(a.loopA + 2);
        Mem::Write<uintptr_t>(missionCountAddr, ModContext::MissionCount);

        // EBP Patch
        BYTE patchEBP[6] = { 0xBD, 0, 0, 0, 0, 0x90 };
        *(uintptr_t*)(&patchEBP[1]) = PtrMissionInfoArray;
        Mem::WriteBytes(a.loopA + 17, patchEBP, 6);

        // Offset Patch
        int negOffset = -(ModContext::MissionCount * ELEMENT_SIZE);
        uintptr_t offsetPatchAddr = a.loopB + 63;
        Mem::Write<BYTE>(offsetPatchAddr, 0x8D);
        Mem::Write<BYTE>(offsetPatchAddr + 1, 0x8D);
        Mem::Write<int>(offsetPatchAddr + 2, negOffset);

        // Loop Limit
        Mem::Write<BYTE>(a.loopC, 0xA1);
        LoopLimit = ModContext::MissionCount;
        Mem::Write<uintptr_t>(a.loopC + 1, (uintptr_t)&LoopLimit);

        // Menu Getters
        RetAddr_MenuTitle = (DWORD)(a.menuTitle + 22);
        Mem::MakeJMP(a.menuTitle + 15, (uintptr_t)Hook_Menu_GetTitle, 2);
        RetAddr_MenuDesc = (DWORD)(a.menuDesc + 19);
        Mem::MakeJMP(a.menuDesc + 12, (uintptr_t)Hook_Menu_GetDesc, 2);

        // NewMissionsArray literal references. Its original location isn't
        // independently anchored - it sits right after ChapterReqs's array in the
        // static layout (+0x24), with one reference site using a -4-adjusted base
        // (+0x20) instead.
        if (ChapterReqs::ArrayAddr != 0) {
            PatchAllLiteralRefs(ChapterReqs::ArrayAddr + 0x24, ptrNewData);
            PatchAllLiteralRefs(ChapterReqs::ArrayAddr + 0x20, ptrNewData - 4);
        }
        else if (ModContext::EnableConsole) {
            std::cout << "[PATCH] NewMissionsArray sites skipped (ChapterReqs anchor unavailable)." << std::endl;
        }

        PatchBoolArrayReferences();
    }
}


namespace Taxi {
    void Hook() {
        if (ModContext::TaxiPtrArray.empty()) return;

        // Get the start address of our array
        uintptr_t startAddress = (uintptr_t)ModContext::TaxiPtrArray.data();

        // Calculate the end address (End Pointer)
        // In assembly, the loop runs while EDI < EndAddress
        uintptr_t endAddress = startAddress + (ModContext::TaxiPtrArray.size() * 4);

        // Both anchors are resolved before writing either - a start patched without
        // its matching end (or vice versa) would leave the loop reading past our
        // array or stopping early, which is worse than not patching at all.
        uintptr_t startSite = Mem::FindPattern("8B 5C 24 ?? A1 ?? ?? ?? ?? BF ?? ?? ?? ??", ".text");
        uintptr_t endSite = Mem::FindPattern("A1 ?? ?? ?? ?? 83 C7 04 81 FF ?? ?? ?? ??", ".text");
        if (startSite == 0 || endSite == 0) {
            if (ModContext::EnableConsole) std::cout << "[PATCH] Taxi anchor(s) not found, skipping." << std::endl;
            return;
        }

        // PATCH 1: Start Address (MOV EDI, START)
        Mem::Write<uintptr_t>(startSite + 10, startAddress);
        // PATCH 2: End Check (CMP EDI, END)
        Mem::Write<uintptr_t>(endSite + 10, endAddress);
    }
}

namespace MusicPlayer {
    // Original function definition
    typedef MCIERROR(WINAPI* mciSendCommandA_t)(MCIDEVICEID, UINT, DWORD_PTR, DWORD_PTR);
    mciSendCommandA_t Original_mciSendCommandA = nullptr;

    // Fake Device ID to identify our "Virtual CD Player"
    const MCIDEVICEID VIRTUAL_CD_ID = 0xBEEF;

    // =============================================================
    // MP3 PLAYBACK (Media Foundation / MFPlay)
    // =============================================================
    bool ComInitialized = false;
    bool MFStarted = false;
    IMFPMediaPlayer* Player = nullptr;

    // MFPlay callback: used only to loop the current track when it ends.
    class PlayerCallback : public IMFPMediaPlayerCallback {
    public:
        STDMETHODIMP_(ULONG) AddRef() { return 1; }
        STDMETHODIMP_(ULONG) Release() { return 1; }
        STDMETHODIMP QueryInterface(REFIID riid, void** ppv) {
            if (riid == IID_IMFPMediaPlayerCallback || riid == IID_IUnknown) {
                *ppv = static_cast<IMFPMediaPlayerCallback*>(this);
                return S_OK;
            }
            *ppv = nullptr;
            return E_NOINTERFACE;
        }

        void STDMETHODCALLTYPE OnMediaPlayerEvent(MFP_EVENT_HEADER* pEventHeader) {
            if (!pEventHeader || FAILED(pEventHeader->hrEvent)) return;

            if (pEventHeader->eEventType == MFP_EVENT_TYPE_PLAYBACK_ENDED && Player) {
                // Seek back to the start and replay, to emulate the game's looping track behavior.
                PROPVARIANT position = {};
                position.vt = VT_I8;
                position.hVal.QuadPart = 0;
                Player->SetPosition(MFP_POSITIONTYPE_100NS, &position);
                Player->Play();
            }
        }
    };
    PlayerCallback Callback;

    void InitPlayer() {
        HRESULT hrCo = CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
        ComInitialized = SUCCEEDED(hrCo);

        if (FAILED(MFStartup(MF_VERSION))) return;
        MFStarted = true;

        MFPCreateMediaPlayer(nullptr, FALSE, MFP_OPTION_NONE, &Callback, nullptr, &Player);
    }

    void ShutdownPlayer() {
        if (Player) {
            Player->Shutdown();
            Player->Release();
            Player = nullptr;
        }
        if (MFStarted) {
            MFShutdown();
            MFStarted = false;
        }
        if (ComInitialized) {
            CoUninitialize();
            ComInitialized = false;
        }
    }

    bool PlayerInitAttempted = false;

    void PlayTrack(int track) {
        // Deferred from Hook()/DllMain: CoInitializeEx/MFStartup spin up Media
        // Foundation's internal worker threads, and doing that while DllMain still
        // holds the loader lock deadlocks the process before it ever reaches the
        // game's main loop. Doing it here instead - triggered by the first real
        // MCI_PLAY - happens long after DllMain has returned, so the lock is free.
        if (!PlayerInitAttempted) {
            PlayerInitAttempted = true;
            InitPlayer();
        }
        if (!Player) return;

        char filename[MAX_PATH];
        sprintf_s(filename, "Music\\Track%02d.mp3", track);

        if (!FileLoading::FileExists(filename)) {
            if (ModContext::EnableConsole) std::cout << "[MUSIC] File not found: " << filename << std::endl;
            return;
        }

        wchar_t widePath[MAX_PATH];
        MultiByteToWideChar(CP_ACP, 0, filename, -1, widePath, MAX_PATH);

        IMFPMediaItem* pItem = nullptr;
        HRESULT hr = Player->CreateMediaItemFromURL(widePath, TRUE, 0, &pItem);
        if (SUCCEEDED(hr) && pItem) {
            Player->SetMediaItem(pItem);
            Player->Play();
            pItem->Release();
            if (ModContext::EnableConsole) std::cout << "[MUSIC] Loop Track: " << track << " -> " << filename << std::endl;
        }
        else if (ModContext::EnableConsole) {
            std::cout << "[MUSIC] Failed to load: " << filename << " (hr=0x" << std::hex << hr << std::dec << ")" << std::endl;
        }
    }

    void StopTrack() {
        if (Player) Player->Stop();
    }

    MCIERROR WINAPI Hook_mciSendCommandA(MCIDEVICEID IDDevice, UINT uMsg, DWORD_PTR fdwCommand, DWORD_PTR dwParam) {

        // 1. MCI_OPEN
        if (uMsg == MCI_OPEN) {
            LPMCI_OPEN_PARMS pOpen = (LPMCI_OPEN_PARMS)dwParam;
            if (pOpen) pOpen->wDeviceID = VIRTUAL_CD_ID;
            return 0;
        }

        // 2. Filter
        if (IDDevice != VIRTUAL_CD_ID && IDDevice != 0 && IDDevice != (MCIDEVICEID)-1) {
            return Original_mciSendCommandA(IDDevice, uMsg, fdwCommand, dwParam);
        }

        // 3. MCI_PLAY
        if (uMsg == MCI_PLAY) {
            LPMCI_PLAY_PARMS pPlay = (LPMCI_PLAY_PARMS)dwParam;

            if (fdwCommand & MCI_FROM) {
                int track = pPlay->dwFrom & 0xFF;
                if (track == 0) {
                    track = 11;
                }
                PlayTrack(track);
            }
            return 0;
        }

        // 4. MCI_STOP / MCI_CLOSE
        if (uMsg == MCI_STOP || uMsg == MCI_CLOSE) {
            StopTrack();
            return 0;
        }

        return 0;
    }

    void Hook() {
        // InitPlayer() is intentionally NOT called here - see PlayTrack().
        Mem::PatchIAT(Mem::FindIATAddress("WINMM.dll", "mciSendCommandA"), (uintptr_t)Hook_mciSendCommandA, (uintptr_t*)&Original_mciSendCommandA);
    }
}

namespace RemoveThreadAffinityPin {
    // The game's frame-timing wait pins its thread to CPU core 0 (SetThreadAffinityMask)
    // around a QueryPerformanceCounter busy-wait loop - a workaround for early-2000s
    // multi-CPU systems where each core had its own unsynced TSC. Modern CPUs have an
    // invariant, cross-core-synced TSC, so the pin is unnecessary - and forcing the
    // thread onto core 0 specifically can make it contend with OS/driver interrupts
    // that also favor core 0, occasionally causing the very stutter this "fix" was
    // meant to prevent.
    //
    // Implemented as an IAT hook (like the other API hooks in this file) rather than
    // patching the two known call sites directly: this way it's a plain "shim" over
    // SetThreadAffinityMask by name - it doesn't care where in the binary the calls
    // live or how many there are, so it can't go stale if a different build adds,
    // removes, or reorders call sites. Confirmed (via VaBank.exe and Clou2.exe
    // disassembly) that neither of the game's two call sites use the return value,
    // so a pure no-op stub is safe - the wait loop and its timing logic are untouched,
    // only the pinning is skipped.
    typedef DWORD_PTR(WINAPI* SetThreadAffinityMask_t)(HANDLE, DWORD_PTR);
    SetThreadAffinityMask_t Original_SetThreadAffinityMask = nullptr;

    DWORD_PTR WINAPI Hook_SetThreadAffinityMask(HANDLE hThread, DWORD_PTR dwThreadAffinityMask) {
        return 1; // pretend success; the game never checks this return value
    }

    void Hook() {
        uintptr_t iatAddr = Mem::FindIATAddress("KERNEL32.dll", "SetThreadAffinityMask");
        if (iatAddr == 0) {
            if (ModContext::EnableConsole) std::cout << "[PATCH] SetThreadAffinityMask import not found, skipping." << std::endl;
            return;
        }
        Mem::PatchIAT(iatAddr, (uintptr_t)Hook_SetThreadAffinityMask, (uintptr_t*)&Original_SetThreadAffinityMask);
        if (ModContext::EnableConsole) std::cout << "[PATCH] SetThreadAffinityMask neutralized (no core-0 pin)." << std::endl;
    }
}

namespace TimerFix {
    // Speed hack: the game reads its clock via timeGetTime(), so scaling how fast
    // that clock advances scales everything driven by it. '+'/'-' step the
    // multiplier between 1x and 10x at runtime; '=' resets to 1x.
    typedef DWORD(WINAPI* timeGetTime_t)();
    timeGetTime_t Original_timeGetTime = nullptr;

    double CurrentMultiplier = 1.0;

    DWORD WINAPI Hook_timeGetTime() {
        static LARGE_INTEGER frequency;
        static LARGE_INTEGER last_real_time;
        static double fake_time_accumulated = 0;
        static bool initialized = false;

        if (!initialized) {
            QueryPerformanceFrequency(&frequency);
            QueryPerformanceCounter(&last_real_time);
            fake_time_accumulated = Original_timeGetTime ? (double)Original_timeGetTime() : (double)timeGetTime();
            initialized = true;
        }

        static bool plus_was_pressed = false;
        static bool minus_was_pressed = false;

        bool plus_is_pressed = (GetAsyncKeyState(VK_OEM_PLUS) & 0x8000) != 0;
        bool minus_is_pressed = (GetAsyncKeyState(VK_OEM_MINUS) & 0x8000) != 0;

        if (plus_is_pressed && !plus_was_pressed) {
            if (CurrentMultiplier < 10.0) {
                CurrentMultiplier += 1.0;
                Beep(600 + (int)(CurrentMultiplier * 100), 100);
            }
        }
        if (minus_is_pressed && !minus_was_pressed) {
            if (CurrentMultiplier > 1.0) {
                CurrentMultiplier -= 1.0;
                Beep(600 + (int)(CurrentMultiplier * 100), 100);
            }
        }
        plus_was_pressed = plus_is_pressed;
        minus_was_pressed = minus_is_pressed;

        LARGE_INTEGER current_time;
        QueryPerformanceCounter(&current_time);

        double realDeltaMs = (double)(current_time.QuadPart - last_real_time.QuadPart) * 1000.0 / (double)frequency.QuadPart;
        last_real_time = current_time;

        // Clamp large deltas (e.g. a fullscreen render hitch) so the accumulated
        // "fake" time doesn't jump the game engine forward all at once.
        if (realDeltaMs > 100.0) realDeltaMs = 100.0;

        fake_time_accumulated += (realDeltaMs * CurrentMultiplier);
        return (DWORD)fake_time_accumulated;
    }

    void Hook() {
        timeBeginPeriod(1);
        uintptr_t iatAddr = Mem::FindIATAddress("WINMM.dll", "timeGetTime");
        if (iatAddr == 0) {
            if (ModContext::EnableConsole) std::cout << "[PATCH] timeGetTime import not found, speed hack disabled." << std::endl;
            return;
        }
        Mem::PatchIAT(iatAddr, (uintptr_t)Hook_timeGetTime, (uintptr_t*)&Original_timeGetTime);
    }
}

namespace SpeedOSD {
    // Small always-on-top, click-through overlay window showing the current speed
    // multiplier in the top-right corner of the screen, visible only while it's
    // above 1x. This draws with plain GDI in its own window rather than hooking
    // into the game's DirectDraw/Direct3D surfaces, so it works the same way
    // regardless of what's rendering the game underneath (including through a
    // compatibility wrapper) - the one thing it needs is that the game isn't
    // running in true exclusive fullscreen, since nothing else can draw on top of
    // that. Windowed/borderless (which this mod already supports) is fine.
    HWND hOverlay = nullptr;
    const int WIDTH = 170;
    const int HEIGHT = 34;

    LRESULT CALLBACK WndProc(HWND hwnd, UINT msg, WPARAM wParam, LPARAM lParam) {
        switch (msg) {
        case WM_TIMER: {
            bool shouldShow = TimerFix::CurrentMultiplier > 1.0;
            bool isVisible = IsWindowVisible(hwnd) != FALSE;
            if (shouldShow != isVisible) {
                ShowWindow(hwnd, shouldShow ? SW_SHOWNOACTIVATE : SW_HIDE);
            }
            if (shouldShow) {
                InvalidateRect(hwnd, nullptr, TRUE);
            }
            return 0;
        }
        case WM_PAINT: {
            PAINTSTRUCT ps;
            HDC hdc = BeginPaint(hwnd, &ps);
            RECT rc;
            GetClientRect(hwnd, &rc);

            HBRUSH bg = CreateSolidBrush(RGB(0, 0, 0)); // matches the color key set below
            FillRect(hdc, &rc, bg);
            DeleteObject(bg);

            SetBkMode(hdc, TRANSPARENT);
            SetTextColor(hdc, RGB(90, 255, 90));
            HFONT font = CreateFontA(-22, 0, 0, 0, FW_BOLD, FALSE, FALSE, FALSE,
                DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS,
                ANTIALIASED_QUALITY, DEFAULT_PITCH | FF_DONTCARE, "Consolas");
            HFONT oldFont = (HFONT)SelectObject(hdc, font);

            char buf[32];
            sprintf_s(buf, "SPEED x%.0f", TimerFix::CurrentMultiplier);
            DrawTextA(hdc, buf, -1, &rc, DT_CENTER | DT_VCENTER | DT_SINGLELINE);

            SelectObject(hdc, oldFont);
            DeleteObject(font);
            EndPaint(hwnd, &ps);
            return 0;
        }
        case WM_ERASEBKGND:
            return 1; // avoid a flash before WM_PAINT fills it in
        case WM_NCHITTEST:
            return HTTRANSPARENT; // click-through
        }
        return DefWindowProc(hwnd, msg, wParam, lParam);
    }

    DWORD WINAPI ThreadProc(LPVOID) {
        WNDCLASSA wc = {};
        wc.lpfnWndProc = WndProc;
        wc.hInstance = GetModuleHandle(NULL);
        wc.lpszClassName = "VaBankSpeedOSD";
        RegisterClassA(&wc);

        int screenW = GetSystemMetrics(SM_CXSCREEN);
        hOverlay = CreateWindowExA(
            WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
            "VaBankSpeedOSD", "", WS_POPUP,
            screenW - WIDTH - 10, 10, WIDTH, HEIGHT,
            nullptr, nullptr, GetModuleHandle(NULL), nullptr);

        if (!hOverlay) return 0;

        // Black pixels are fully transparent; everything else (our text) is opaque.
        SetLayeredWindowAttributes(hOverlay, RGB(0, 0, 0), 0, LWA_COLORKEY);
        SetTimer(hOverlay, 1, 250, nullptr);

        MSG msg;
        while (GetMessage(&msg, nullptr, 0, 0)) {
            TranslateMessage(&msg);
            DispatchMessage(&msg);
        }
        return 0;
    }

    void Hook() {
        CreateThread(nullptr, 0, ThreadProc, nullptr, 0, nullptr);
    }
}

void OpenConsole() {
    if (!AttachConsole(ATTACH_PARENT_PROCESS)) {
        if (!AllocConsole()) return;
    }
    freopen_s((FILE**)stdout, "CONOUT$", "w", stdout);
    freopen_s((FILE**)stderr, "CONOUT$", "w", stderr);
    std::cout.clear();
    std::ios::sync_with_stdio(true);
}
// =============================================================
// INIT & CONFIG
// =============================================================
void LoadConfig() {
    std::string IniPath;
    char path[MAX_PATH];
    GetModuleFileNameA(NULL, path, MAX_PATH);
    std::string fullPath = path;
    // Construct path to \mods\config.ini
    IniPath = fullPath.substr(0, fullPath.find_last_of("\\/")) + "\\config.ini";
    const char* cPath = IniPath.c_str();

    // 1. Load Settings
    ModContext::EnableConsole = GetPrivateProfileIntA("Settings", "OpenConsole", 0, cPath);
    ModContext::EnableLog = GetPrivateProfileIntA("Settings", "EnableLog", 0, cPath);
    ModContext::EditorMode = GetPrivateProfileIntA("Settings", "EditorMode", 0, cPath);
    ModContext::WindowedMode = GetPrivateProfileIntA("Settings", "WindowedMode", 0, cPath);
    ModContext::NoCd = GetPrivateProfileIntA("Settings", "NoCd", 1, cPath);
    ModContext::EnableMusicHook = GetPrivateProfileIntA("Settings", "EnableMusicHook", 1, cPath);

    // 2. Load Mission Count
    ModContext::MissionCount = GetPrivateProfileIntA("Missions", "Count", ModContext::MissionCount, cPath);

    // Load Game File Name
    char strBuffer[256];
    GetPrivateProfileStringA("Main", "GameFile", "VaBank.wld", strBuffer, 256, cPath);
    ModContext::GameFile = strBuffer;

    // Load Dialog File Name
    GetPrivateProfileStringA("Main", "DialogFile", "data\\dialogs_rus.txt", strBuffer, 256, cPath);
    ModContext::DialogFile = strBuffer;

    // 3. Load Mission Levels
    ModContext::NewMissionsArray.reserve(ModContext::MissionCount);
    for (int i = 0; i < ModContext::MissionCount; i++) {
        char key[32];
        wsprintfA(key, "Level_%d", i + 1);
        int val = GetPrivateProfileIntA("Missions", key, 1, cPath);
        ModContext::NewMissionsArray.push_back(val);
    }

    // 4. Load Remap Missions
    const int SECTION_BUF_SIZE = 4096;
    std::vector<char> buffer(SECTION_BUF_SIZE);
    GetPrivateProfileSectionA("RemapMissions", buffer.data(), SECTION_BUF_SIZE, cPath);
    char* p = buffer.data();
    while (*p) {
        int from = 0, to = 0;
        if (sscanf_s(p, "Level_%d=%d", &from, &to)) {
            ModContext::MissionRemapMap[from] = to;
        }
        p += strlen(p) + 1;
    }

    // 5. Load Chapter Requirements
    for (int i = 0; i < 9; i++) {
        char key[32];
        wsprintfA(key, "ChapterReq_%d", i + 2);
        int val = GetPrivateProfileIntA("ChapterSettings", key, ModContext::ChapterReqs[i], cPath);
        ModContext::ChapterReqs[i] = val;
    }

    // 6. Load Special Missions & Building IDs
    // Default values (11, 17, 16, 15, 18) are used if not found in INI
    ModContext::SpecialMission1 = GetPrivateProfileIntA("SpecialMission", "FirstSpecialMission", 11, cPath);
    ModContext::SpecialMission2 = GetPrivateProfileIntA("SpecialMission", "SecondSpecialMission", 17, cPath);
    ModContext::SpecialMission3 = GetPrivateProfileIntA("SpecialMission", "ThirdSpecialMission", 16, cPath);
    ModContext::BarracksID = GetPrivateProfileIntA("SpecialMission", "Barracks", 15, cPath);
    ModContext::ConcernID = GetPrivateProfileIntA("SpecialMission", "Concern", 18, cPath);

    // Read the total number of records
    int TaxiCount = GetPrivateProfileIntA("Taxi", "Count", 0, cPath);
    if (TaxiCount == 0) return;
    // Reserve memory to avoid unnecessary allocations
    ModContext::TaxiNames.reserve(TaxiCount);
    ModContext::TaxiPtrArray.reserve(TaxiCount);

    for (int i = 0; i < TaxiCount; i++) {
        char key[32];
        char value[64];
        // Format the key: Cab_1, Cab_2, Cab_3...
        wsprintfA(key, "Cab_%d", i + 1);

        // Read the value. Default value is "" (empty string)
        GetPrivateProfileStringA("Taxi", key, "", value, 64, cPath);

        // SEPARATOR LOGIC:
        if (strlen(value) > 0) {
            // If text exists (e.g. "CAB_01"), save it
            ModContext::TaxiNames.push_back(std::string(value));
            // And add a pointer to this text to the array
            ModContext::TaxiPtrArray.push_back(ModContext::TaxiNames.back().c_str());
        }
        else {
            // If the string is empty (length 0), it is a SEPARATOR.
            // The game expects a clean 0 (NULL) here, not a pointer to an empty string.
            ModContext::TaxiPtrArray.push_back(nullptr);
        }
    }
}

void Init() {
    LoadConfig();

    // Check config for Console
    if (ModContext::EnableConsole) {
        OpenConsole();
    }

    // Check config for Log
    // This flag's set-instruction is one of eight near-identical
    // "cmp.../pop edi/pop esi/mov byte ptr[addr],1" blocks in the same INI-parsing
    // dispatcher; the six actual config flags occupy a fixed position among them
    // that mirrors source order, confirmed stable across both builds checked -
    // EnableLog is always the 6th (index 5).
    if (ModContext::EnableLog) {
        Mem::Write<BYTE>(0x0057F220, 1);
    }

    // Check config for Editor Mode
    if (ModContext::EditorMode) {
        Mem::Write<BYTE>(0x0056d31e, 0);
    }

    // Check config for Windowed Mode
    if (ModContext::WindowedMode) {
        Mem::Write<BYTE>(0x0057F21A, 1);
    }

    if (ModContext::NoCd) {
        Mem::Write<BYTE>(0x0047f716, 0xEB);
    }

    // =========================================================
    // Hook file resources loading
    // =========================================================
    std::cout << "[SYSTEM] Patching Import Address Table..." << std::endl;
    FileLoading::Hook();
    std::cout << "[SYSTEM] Import Address Table Patched." << std::endl;

    // Hook Chapter Requirements
    std::cout << "[SYSTEM] Hooking ChapterReqs..." << std::endl;
    ChapterReqs::Hook();
    std::cout << "[SYSTEM] ChapterReqs Hooked." << std::endl;

    // Hook Missions
    std::cout << "[SYSTEM] Hooking Missions..." << std::endl;
    Missions::Hook();
    std::cout << "[SYSTEM] Missions Hooked." << std::endl;

    // Hook Mission Images
    std::cout << "[SYSTEM] Hooking CreateMissionImages..." << std::endl;
    CreateMissionImages::Hook();
    std::cout << "[SYSTEM] CreateMissionImages Hooked." << std::endl;

    std::cout << "[SYSTEM] Hooking Taxi..." << std::endl;
    Taxi::Hook();
    std::cout << "[SYSTEM] Taxi Hooked." << std::endl;

    if (ModContext::EnableMusicHook) {
        std::cout << "[SYSTEM] Hooking Music Player..." << std::endl;
        MusicPlayer::Hook();
        std::cout << "[SYSTEM] Music Player Hooked." << std::endl;
    }
    else {
        std::cout << "[SYSTEM] Music Player Skipped (Disabled in Config)." << std::endl;
    }

    std::cout << "[SYSTEM] Removing thread affinity pin..." << std::endl;
    RemoveThreadAffinityPin::Hook();

    std::cout << "[SYSTEM] Hooking speed hack (+/-)..." << std::endl;
    TimerFix::Hook();
    //SpeedOSD::Hook();

    // =========================================================
    // Apply Hex Patches from Config
    // =========================================================

    // 1-3. Special Missions (chain of three cmp/je checks against the mission ID,
    // immediately preceded by "mov BYTE PTR ds:[X],1"). The array-address operand of
    // that mov varies by build, so it's wildcarded; the cmp/je opcodes and the default
    // mission IDs (0xb, 0x11, 0x10) are confirmed identical across builds checked.
    {
        uintptr_t chain = Mem::FindPattern(
            "C6 05 ?? ?? ?? ?? 01 83 F8 0B 74 0A 83 F8 11 74 05 83 F8 10 75 07", ".text");
        if (chain == 0) {
            if (ModContext::EnableConsole) std::cout << "[PATCH] SpecialMission chain pattern not found, skipping." << std::endl;
        }
        else {
            std::cout << "[PATCH] Setting FirstSpecialMission to: " << ModContext::SpecialMission1 << std::endl;
            Mem::Write<BYTE>(chain + 9, static_cast<BYTE>(ModContext::SpecialMission1));

            std::cout << "[PATCH] Setting SecondSpecialMission to: " << ModContext::SpecialMission2 << std::endl;
            Mem::Write<BYTE>(chain + 14, static_cast<BYTE>(ModContext::SpecialMission2));

            std::cout << "[PATCH] Setting ThirdSpecialMission to: " << ModContext::SpecialMission3 << std::endl;
            Mem::Write<BYTE>(chain + 19, static_cast<BYTE>(ModContext::SpecialMission3));
        }
    }

    // 4. Barracks ID: "mov eax,[edx] / cmp eax,0xe / jne ..."
    {
        uintptr_t site = Mem::FindPattern("8B 02 83 F8 0E", ".text");
        if (site == 0) {
            if (ModContext::EnableConsole) std::cout << "[PATCH] Barracks pattern not found, skipping." << std::endl;
        }
        else {
            std::cout << "[PATCH] Setting Barracks ID to: " << ModContext::BarracksID << std::endl;
            Mem::Write<BYTE>(site + 4, static_cast<BYTE>(ModContext::BarracksID - 1));
        }
    }

    // 5. Concern ID: "cmp eax,0x11 / mov eax,[esi+0xf0] / jne ..."
    {
        uintptr_t site = Mem::FindPattern("83 F8 11 8B 86 F0 00 00 00", ".text");
        if (site == 0) {
            if (ModContext::EnableConsole) std::cout << "[PATCH] Concern pattern not found, skipping." << std::endl;
        }
        else {
            std::cout << "[PATCH] Setting Concern ID to: " << ModContext::ConcernID << std::endl;
            Mem::Write<BYTE>(site + 2, static_cast<BYTE>(ModContext::ConcernID - 1));
        }
    }


    // 1. Patch GameFile String Reference
    // "cmp BYTE PTR ds:[EditorModeFlag],bl / je +X / mov edi,<default-worldfile-string>"
    {
        uintptr_t site = Mem::FindPattern("38 1D ?? ?? ?? ?? 74 ?? BF ?? ?? ?? ??", ".text");
        if (site == 0) {
            if (ModContext::EnableConsole) std::cout << "[PATCH] GameFile pattern not found, skipping." << std::endl;
        }
        else {
            std::cout << "[PATCH] Setting GameFile to: " << ModContext::GameFile << std::endl;
            Mem::Write<uintptr_t>(site + 9, (uintptr_t)ModContext::GameFile.c_str());
        }
    }

    // 2. Patch DialogFile String Reference
    // The "default dialog file" if/else diamond: two alternate CString pushes
    // converging on the same call; we only patch the second (fallback) branch,
    // matching the original hardcoded-address behavior.
    {
        uintptr_t site = Mem::FindPattern(
            "74 ?? 8D 4C 24 ?? 68 ?? ?? ?? ?? 51 EB ?? 8D 54 24 ?? 68 ?? ?? ?? ?? 52 FF 15 ?? ?? ?? ??", ".text");
        if (site == 0) {
            if (ModContext::EnableConsole) std::cout << "[PATCH] DialogFile pattern not found, skipping." << std::endl;
        }
        else {
            std::cout << "[PATCH] Setting DialogFile to: " << ModContext::DialogFile << std::endl;
            Mem::Write<uintptr_t>(site + 19, (uintptr_t)ModContext::DialogFile.c_str());
        }
    }


    // RemapMissionInMenu::Hook(); // disabled

    std::cout << "[SYSTEM] Init Completed." << std::endl;
}

BOOL APIENTRY DllMain(HMODULE hModule, DWORD reason, LPVOID lpReserved) {
    if (reason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(hModule);
        Init();
    }
    else if (reason == DLL_PROCESS_DETACH) {
        if (ModContext::EnableMusicHook) {
            MusicPlayer::ShutdownPlayer();
        }
    }
    return TRUE;
}