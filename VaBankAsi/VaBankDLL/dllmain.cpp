#include <windows.h>
#include <vector>
#include <map>
#include <iostream>
#include <fstream> // Added for file reading


// =============================================================
// MEMORY UTILITIES
// =============================================================
namespace Mem {
    uintptr_t Base() {
        static uintptr_t base = (uintptr_t)GetModuleHandle(NULL);
        return base;
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

    FindResourceA_t Original_FindResourceA = nullptr;
    LoadResource_t  Original_LoadResourceA = nullptr;
    LockResource_t  Original_LockResource = nullptr;

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

    void Hook() {
        Mem::PatchIAT(0x00553138, (uintptr_t)Hook_FindResourceA, (uintptr_t*)&Original_FindResourceA);
        Mem::PatchIAT(0x005530a8, (uintptr_t)Hook_LoadResource, (uintptr_t*)&Original_LoadResourceA);
        Mem::PatchIAT(0x005530b0, (uintptr_t)Hook_LockResource, (uintptr_t*)&Original_LockResource);
    }
}

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

    // Function Pointers for InitMissionImages
    typedef void(__thiscall* tModelConstructor)(void* thisPtr, int arg1);
    tModelConstructor Call_ModelConstructor = (tModelConstructor)0x004C67D0;

    typedef void(__cdecl* tModelSetup)(void* resourcePtr, void* instancePtr);
    tModelSetup Call_ModelSetup = (tModelSetup)0x0042DC20;

    typedef uintptr_t(__cdecl* tCreateUIObject)(int id, const char* name, int arg3);
    tCreateUIObject Call_CreateUIObject = (tCreateUIObject)0x004A2C40;

    uintptr_t* Game_Ptr_Context = (uintptr_t*)0x0057F284;

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
        Mem::Write<uintptr_t>(0x004663AB + 3, newArrayAddress - 4);
        Mem::Write<uintptr_t>(0x0045E3A0 + 3, newArrayAddress);
        Mem::Write<uintptr_t>(0x00457D3F + 3, newArrayAddress);
        Mem::Write<uintptr_t>(0x0045660B + 3, newArrayAddress - 4);

        std::cout << "[SYSTEM] Icons Initialized." << std::endl;
    }

    // Image Setup Hook
    DWORD RetAddr_ImageInit = 0x00493B6D + 5;
    DWORD Func_OriginalCall = 0x004925D0;

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

    void Hook() {
        Mem::MakeJMP(0x00493B6D, (uintptr_t)Hook_SetupImages, 0);
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
    // =============================================================
    DWORD RetAddr_Init1 = 0x00450E2F;
    __declspec(naked) void Hook_InitArray1() {
        __asm {
            push ModContext::MissionCount
            mov ecx, PtrMissionNameArray
            push 0x8
            push ecx
            jmp RetAddr_Init1
        }
    }
    DWORD RetAddr_Init2 = 0x00450E4F;
    __declspec(naked) void Hook_InitArray2() {
        __asm {
            push ModContext::MissionCount
            mov edx, PtrMissionInfoArray
            push 0x8
            push edx
            jmp RetAddr_Init2
        }
    }
    DWORD RetAddr_MenuTitle = 0x0045A0EB + 7;
    __declspec(naked) void Hook_Menu_GetTitle() {
        __asm {
            mov edx, PtrMissionNameArray
            lea edx, [edx + eax * 8]
            jmp RetAddr_MenuTitle
        }
    }
    DWORD RetAddr_MenuDesc = 0x0045A1FE + 7;
    __declspec(naked) void Hook_Menu_GetDesc() {
        __asm {
            mov eax, PtrMissionInfoArray
            lea eax, [eax + edx * 8]
            jmp RetAddr_MenuDesc
        }
    }

    void PatchBoolArrayReferences() {
        uintptr_t newAddr = PtrMissionCompletelyArray;
        uintptr_t newAddrMinus1 = newAddr - 1;

        Mem::Write<uintptr_t>(0x00495d38 + 1, newAddr);
        Mem::Write<uintptr_t>(0x00495734 + 1, newAddr);
        Mem::Write<uintptr_t>(0x004a8e52 + 2, newAddr);
        Mem::Write<uintptr_t>(0x004a8e7a + 2, newAddr);
        Mem::Write<uintptr_t>(0x00484d19 + 2, newAddr);
        Mem::Write<uintptr_t>(0x004a8b93 + 2, newAddr);
        Mem::Write<uintptr_t>(0x0045e3e5 + 2, newAddr);
        Mem::Write<uintptr_t>(0x0045e335 + 1, newAddr);
        Mem::Write<uintptr_t>(0x0045e35e + 3, newAddr);
        Mem::Write<uintptr_t>(0x004855bd + 2, newAddrMinus1);
        Mem::Write<uintptr_t>(0x00484cff + 2, newAddrMinus1);
    }

    void Hook() {
        size_t arraySize = ModContext::MissionCount * ELEMENT_SIZE;
        size_t boolSize = ModContext::MissionCount * sizeof(bool);
        size_t totalSize = (arraySize * 2) + boolSize + 1024;

        RawBuffer = (unsigned char*)VirtualAlloc(NULL, totalSize, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
        PtrMissionNameArray = (uintptr_t)RawBuffer;
        PtrMissionInfoArray = (uintptr_t)(RawBuffer + arraySize);
        PtrMissionCompletelyArray = (uintptr_t)(RawBuffer + (arraySize * 2));

        uintptr_t ptrNewData = (uintptr_t)ModContext::NewMissionsArray.data();
        uintptr_t base = Mem::Base();

        // =========================================================
        // 3. APPLY HOOKS & PATCHES
        // =========================================================

        // Arrays Init
        Mem::MakeJMP(0x00450E24, (uintptr_t)Hook_InitArray1, 6);
        Mem::MakeJMP(0x00450E44, (uintptr_t)Hook_InitArray2, 6);

        // EBP Patch
        BYTE patchEBP[6] = { 0xBD, 0, 0, 0, 0, 0x90 };
        *(uintptr_t*)(&patchEBP[1]) = PtrMissionInfoArray;
        Mem::WriteBytes(0x00457646, patchEBP, 6);

        // Offset Patch
        int negOffset = -(ModContext::MissionCount * ELEMENT_SIZE);
        Mem::Write<BYTE>(0x00457685, 0x8D);
        Mem::Write<BYTE>(0x00457686, 0x8D);
        Mem::Write<int>(0x00457687, negOffset);

        // Loop Limit
        Mem::Write<BYTE>(0x004576D0, 0xA1);
        LoopLimit = ModContext::MissionCount;
        Mem::Write<uintptr_t>(0x004576D1, (uintptr_t)&LoopLimit);

        // Menu Getters
        Mem::MakeJMP(0x0045A0EB, (uintptr_t)Hook_Menu_GetTitle, 2);
        Mem::MakeJMP(0x0045A1FE, (uintptr_t)Hook_Menu_GetDesc, 2);

        // Data Pointers
        Mem::Write<uintptr_t>(base + 0x15b5c8, ModContext::MissionCount);
        Mem::Write<uintptr_t>(base + 0x84d10 + 1, ptrNewData);
        Mem::Write<uintptr_t>(base + 0x8556a + 3, ptrNewData - 4);
        Mem::Write<uintptr_t>(base + 0x5e3b1 + 3, ptrNewData);
        Mem::Write<uintptr_t>(base + 0x5e3d1 + 3, ptrNewData);

        PatchBoolArrayReferences();
    }
}

namespace ChapterReqs {
    void Hook() {
        for (int i = 0; i < 9; i++) {
            Mem::Write<int>(0x571840 + (i * 4), ModContext::ChapterReqs[i]);
        }
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

        // PATCH 1: Start Address (MOV EDI, START) -> 00507213
        Mem::Write<uintptr_t>(0x00507213 + 1, startAddress);

        // PATCH 2: End Check (CMP EDI, END) -> 00507399
        // Offset +2, because the opcode is 81 FF
        Mem::Write<uintptr_t>(0x00507399 + 2, endAddress);
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
    ModContext::NoCd = GetPrivateProfileIntA("Settings", "NoCd", 0, cPath);

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
    if (ModContext::EnableLog) {
        Mem::Write<BYTE>(0x0057F220, 1);
    }

    // Check config for Editor Mode
    if (ModContext::EditorMode) {
        Mem::Write<BYTE>(0x0056d31e, 0);
    }

    // Check config for Windowed Mode
    // Address 0x0057F21A controls windowed state (1 = windowed)
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


    // =========================================================
    // Apply Hex Patches from Config
    // =========================================================

    // 1. First Special Mission
    // 00485da7 -> 83 f8 0b -> Patch address 00485da9
    std::cout << "[PATCH] Setting FirstSpecialMission to: " << ModContext::SpecialMission1 << std::endl;
    Mem::Write<BYTE>(0x00485da9, static_cast<BYTE>(ModContext::SpecialMission1));

    // 2. Second Special Mission
    // 00485dac -> 83 f8 11 -> Patch address 00485dae
    std::cout << "[PATCH] Setting SecondSpecialMission to: " << ModContext::SpecialMission2 << std::endl;
    Mem::Write<BYTE>(0x00485dae, static_cast<BYTE>(ModContext::SpecialMission2));

    // 3. Third Special Mission
    // 00485db1 -> 83 f8 10 -> Patch address 00485db3
    std::cout << "[PATCH] Setting ThirdSpecialMission to: " << ModContext::SpecialMission3 << std::endl;
    Mem::Write<BYTE>(0x00485db3, static_cast<BYTE>(ModContext::SpecialMission3));


    // 4. Barracks ID
    // 0045999A: cmp eax, 0E -> 0045999C is the value
    // Use the value loaded from config directly.
    std::cout << "[PATCH] Setting Barracks ID to: " << ModContext::BarracksID << std::endl;
    Mem::Write<BYTE>(0x0045999C, static_cast<BYTE>(ModContext::BarracksID - 1));

    // 5. Concern ID
    std::cout << "[PATCH] Setting Concern ID to: " << ModContext::ConcernID << std::endl;
    Mem::Write<BYTE>(0x00459a78 + 2, static_cast<BYTE>(ModContext::ConcernID - 1));


    // 1. Patch GameFile String Reference
    // Original ASM: 0047fd59: BF 90 D6 56 00 (MOV EDI, 0x0056D690)
    // We update the address in the instruction (0x0047fd59 + 1) to point to our string
    std::cout << "[PATCH] Setting GameFile to: " << ModContext::GameFile << std::endl;
    Mem::Write<uintptr_t>(0x0047fd5a, (uintptr_t)ModContext::GameFile.c_str());

    // 2. Patch DialogFile String Reference
    // Original ASM: 0047d881: 68 D0 D4 56 00 (PUSH 0x0056D4D0)
    // We update the address in the instruction (0x0047d881 + 1) to point to our string
    std::cout << "[PATCH] Setting DialogFile to: " << ModContext::DialogFile << std::endl;
    Mem::Write<uintptr_t>(0x0047d882, (uintptr_t)ModContext::DialogFile.c_str());


    // RemapMissionInMenu::Hook(); // disabled

    std::cout << "[SYSTEM] Init Completed." << std::endl;
}

BOOL APIENTRY DllMain(HMODULE hModule, DWORD reason, LPVOID lpReserved) {
    if (reason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(hModule);
        Init();
    }
    return TRUE;
}