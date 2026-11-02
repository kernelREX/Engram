// Engram, the RED4ext half.
//
// redscript can build the menus but cannot touch a file or a socket, and the CET sandbox
// cannot run a program, so everything Engram actually does has to live in a native plugin.
// This file is the plugin's edge: it registers the class redscript calls into, and nothing
// more. The work goes in its own translation units so it can be tested without a game.
//
// This first version deliberately does very little. It proves the parts everything else
// depends on, in the order they can break: the DLL loads under RED4ext, the class reaches
// the RTTI system, redscript can call it, strings and arrays survive the boundary, and the
// process can read the save folder from inside the game.

#include <windows.h>

#include <RED4ext/RED4ext.hpp>
#include <RED4ext/RTTITypes.hpp>
#include <RED4ext/Scripting/IScriptable.hpp>

#include <filesystem>
#include <functional>
#include <string>
#include <vector>

#include "Jobs.hpp"
#include "SaveFolder.hpp"
#include "Version.hpp"

namespace
{
struct EngramNative : RED4ext::IScriptable
{
    RED4ext::CClass* GetNativeType();
};

RED4ext::TTypedClass<EngramNative> g_class("EngramNative");

RED4ext::CClass* EngramNative::GetNativeType()
{
    return &g_class;
}

RED4ext::v1::PluginHandle g_handle = nullptr;
const RED4ext::v1::Sdk* g_sdk = nullptr;

void Log(const std::string& aMessage)
{
    if (g_sdk && g_sdk->logger)
    {
        g_sdk->logger->Info(g_handle, aMessage.c_str());
    }
}

void LogError(const std::string& aMessage)
{
    if (g_sdk && g_sdk->logger)
    {
        g_sdk->logger->Error(g_handle, aMessage.c_str());
    }
}

// Every native takes the same four parameters, and has to step the frame's code pointer
// past ParamEnd itself even when it reads no arguments.
void GetVersion(RED4ext::IScriptable*, RED4ext::CStackFrame* aFrame, RED4ext::CString* aOut, int64_t)
{
    aFrame->code++;
    if (aOut)
    {
        *aOut = RED4ext::CString(engram::kVersion);
    }
}

void GetSaveFolder(RED4ext::IScriptable*, RED4ext::CStackFrame* aFrame, RED4ext::CString* aOut, int64_t)
{
    aFrame->code++;
    if (!aOut)
    {
        return;
    }

    std::string resolved;
    try
    {
        resolved = engram::SaveFolder().string();
    }
    catch (const std::exception& exc)
    {
        LogError(std::string("could not resolve the save folder: ") + exc.what());
    }
    *aOut = RED4ext::CString(resolved.c_str());
}

void GetSaveNames(RED4ext::IScriptable*, RED4ext::CStackFrame* aFrame,
                  RED4ext::DynArray<RED4ext::CString>* aOut, int64_t)
{
    aFrame->code++;
    if (!aOut)
    {
        return;
    }

    std::vector<std::string> names;
    try
    {
        names = engram::ListSaveFolders(engram::SaveFolder());
    }
    catch (const std::exception& exc)
    {
        LogError(std::string("could not list saves: ") + exc.what());
    }

    aOut->Clear();
    aOut->Reserve(static_cast<uint32_t>(names.size()));
    for (const auto& name : names)
    {
        aOut->PushBack(RED4ext::CString(name.c_str()));
    }
}

// Natives that take arguments have to read them off the frame themselves, in order, and
// then step past ParamEnd.
RED4ext::CString ReadString(RED4ext::CStackFrame* aFrame)
{
    RED4ext::CString value;
    RED4ext::GetParameter(aFrame, &value);
    return value;
}

int32_t ReadInt(RED4ext::CStackFrame* aFrame)
{
    int32_t value = 0;
    RED4ext::GetParameter(aFrame, &value);
    return value;
}

bool ReadBool(RED4ext::CStackFrame* aFrame)
{
    bool value = false;
    RED4ext::GetParameter(aFrame, &value);
    return value;
}

void StartShare(RED4ext::IScriptable*, RED4ext::CStackFrame* aFrame, int32_t* aOut, int64_t)
{
    const auto name = ReadString(aFrame);
    const auto hours = ReadInt(aFrame);
    aFrame->code++;
    const auto job = engram::StartShare(name.c_str() ? name.c_str() : "", hours);
    if (aOut)
    {
        *aOut = job;
    }
}

void StartPackToFile(RED4ext::IScriptable*, RED4ext::CStackFrame* aFrame, int32_t* aOut,
                     int64_t)
{
    const auto name = ReadString(aFrame);
    aFrame->code++;
    const auto job = engram::StartPackToFile(name.c_str() ? name.c_str() : "");
    if (aOut)
    {
        *aOut = job;
    }
}

void StartOpenFile(RED4ext::IScriptable*, RED4ext::CStackFrame* aFrame, int32_t* aOut, int64_t)
{
    const auto name = ReadString(aFrame);
    aFrame->code++;
    const auto job = engram::StartOpenFile(name.c_str() ? name.c_str() : "");
    if (aOut)
    {
        *aOut = job;
    }
}

void GetPackedFiles(RED4ext::IScriptable*, RED4ext::CStackFrame* aFrame,
                    RED4ext::DynArray<RED4ext::CString>* aOut, int64_t)
{
    aFrame->code++;
    if (!aOut)
    {
        return;
    }
    const auto names = engram::PackedFiles();
    aOut->Clear();
    aOut->Reserve(static_cast<uint32_t>(names.size()));
    for (const auto& name : names)
    {
        aOut->PushBack(RED4ext::CString(name.c_str()));
    }
}

void StartFetch(RED4ext::IScriptable*, RED4ext::CStackFrame* aFrame, int32_t* aOut, int64_t)
{
    const auto code = ReadString(aFrame);
    aFrame->code++;
    const auto job = engram::StartFetch(code.c_str() ? code.c_str() : "");
    if (aOut)
    {
        *aOut = job;
    }
}

void StartWrite(RED4ext::IScriptable*, RED4ext::CStackFrame* aFrame, int32_t* aOut, int64_t)
{
    const auto fetchJob = ReadInt(aFrame);
    const auto force = ReadBool(aFrame);
    aFrame->code++;
    const auto job = engram::StartWrite(fetchJob, force);
    if (aOut)
    {
        *aOut = job;
    }
}

void JobKind(RED4ext::IScriptable*, RED4ext::CStackFrame* aFrame, int32_t* aOut, int64_t)
{
    const auto job = ReadInt(aFrame);
    aFrame->code++;
    if (aOut)
    {
        *aOut = static_cast<int32_t>(engram::Report(job).kind);
    }
}

void JobModded(RED4ext::IScriptable*, RED4ext::CStackFrame* aFrame, bool* aOut, int64_t)
{
    const auto job = ReadInt(aFrame);
    aFrame->code++;
    if (aOut)
    {
        *aOut = engram::Report(job).modded;
    }
}

void JobState(RED4ext::IScriptable*, RED4ext::CStackFrame* aFrame, int32_t* aOut, int64_t)
{
    const auto job = ReadInt(aFrame);
    aFrame->code++;
    if (aOut)
    {
        *aOut = static_cast<int32_t>(engram::Report(job).state);
    }
}

void JobMessage(RED4ext::IScriptable*, RED4ext::CStackFrame* aFrame, RED4ext::CString* aOut, int64_t)
{
    const auto job = ReadInt(aFrame);
    aFrame->code++;
    if (aOut)
    {
        *aOut = RED4ext::CString(engram::Report(job).message.c_str());
    }
}

void JobCode(RED4ext::IScriptable*, RED4ext::CStackFrame* aFrame, RED4ext::CString* aOut, int64_t)
{
    const auto job = ReadInt(aFrame);
    aFrame->code++;
    if (aOut)
    {
        *aOut = RED4ext::CString(engram::Report(job).code.c_str());
    }
}

void JobBlocked(RED4ext::IScriptable*, RED4ext::CStackFrame* aFrame, bool* aOut, int64_t)
{
    const auto job = ReadInt(aFrame);
    aFrame->code++;
    if (aOut)
    {
        *aOut = engram::Report(job).blocked;
    }
}

void JobFindings(RED4ext::IScriptable*, RED4ext::CStackFrame* aFrame,
                 RED4ext::DynArray<RED4ext::CString>* aOut, int64_t)
{
    const auto job = ReadInt(aFrame);
    aFrame->code++;
    if (!aOut)
    {
        return;
    }
    const auto report = engram::Report(job);
    aOut->Clear();
    aOut->Reserve(static_cast<uint32_t>(report.findings.size()));
    for (const auto& line : report.findings)
    {
        aOut->PushBack(RED4ext::CString(line.c_str()));
    }
}

void CancelJob(RED4ext::IScriptable*, RED4ext::CStackFrame* aFrame, void*, int64_t)
{
    const auto job = ReadInt(aFrame);
    aFrame->code++;
    engram::Cancel(job);
}

void ForgetJobs(RED4ext::IScriptable*, RED4ext::CStackFrame* aFrame, void*, int64_t)
{
    aFrame->code++;
    engram::Forget();
}
} // namespace

RED4EXT_C_EXPORT void RED4EXT_CALL RegisterTypes()
{
    RED4ext::CNamePool::Add("EngramNative");

    g_class.flags = {.isNative = true};
    RED4ext::CRTTISystem::Get()->RegisterType(&g_class);
}

RED4EXT_C_EXPORT void RED4EXT_CALL PostRegisterTypes()
{
    auto* rtti = RED4ext::CRTTISystem::Get();
    g_class.parent = rtti->GetClass("IScriptable");

    const RED4ext::CBaseFunction::Flags flags = {.isNative = true, .isStatic = true};

    {
        auto* func = RED4ext::CClassStaticFunction::Create(&g_class, "Version", "Version", &GetVersion);
        func->flags = flags;
        func->SetReturnType("String");
        g_class.RegisterFunction(func);
    }

    {
        auto* func = RED4ext::CClassStaticFunction::Create(&g_class, "SaveFolder", "SaveFolder", &GetSaveFolder);
        func->flags = flags;
        func->SetReturnType("String");
        g_class.RegisterFunction(func);
    }

    {
        auto* func = RED4ext::CClassStaticFunction::Create(&g_class, "SaveNames", "SaveNames", &GetSaveNames);
        func->flags = flags;
        func->SetReturnType("array:String");
        g_class.RegisterFunction(func);
    }

    struct Native
    {
        const char* name;
        void* handler;
        const char* returns;
        std::vector<const char*> takes;
    };

    const Native natives[] = {
        {"StartShare", &StartShare, "Int32", {"String", "Int32"}},
        {"StartFetch", &StartFetch, "Int32", {"String"}},
        {"StartPackToFile", &StartPackToFile, "Int32", {"String"}},
        {"StartOpenFile", &StartOpenFile, "Int32", {"String"}},
        {"PackedFiles", &GetPackedFiles, "array:String", {}},
        {"StartWrite", &StartWrite, "Int32", {"Int32", "Bool"}},
        {"JobState", &JobState, "Int32", {"Int32"}},
        {"JobKind", &JobKind, "Int32", {"Int32"}},
        {"JobModded", &JobModded, "Bool", {"Int32"}},
        {"JobMessage", &JobMessage, "String", {"Int32"}},
        {"JobCode", &JobCode, "String", {"Int32"}},
        {"JobBlocked", &JobBlocked, "Bool", {"Int32"}},
        {"JobFindings", &JobFindings, "array:String", {"Int32"}},
        {"CancelJob", &CancelJob, nullptr, {"Int32"}},
        {"ForgetJobs", &ForgetJobs, nullptr, {}},
    };

    for (const auto& native : natives)
    {
        auto* func = RED4ext::CClassStaticFunction::Create(
            &g_class, native.name, native.name,
            reinterpret_cast<RED4ext::ScriptingFunction_t<void*>>(native.handler));
        func->flags = flags;
        for (const auto* takes : native.takes)
        {
            func->AddParam(takes, "arg");
        }
        if (native.returns)
        {
            func->SetReturnType(native.returns);
        }
        g_class.RegisterFunction(func);
    }

    Log("Engram " + std::string(engram::kVersion) + " registered its natives");
}

RED4EXT_C_EXPORT bool RED4EXT_CALL Main(RED4ext::v1::PluginHandle aHandle, RED4ext::v1::EMainReason aReason,
                                        const RED4ext::v1::Sdk* aSdk)
{
    switch (aReason)
    {
    case RED4ext::v1::EMainReason::Load:
    {
        g_handle = aHandle;
        g_sdk = aSdk;

        // The plugin sits at <game>/red4ext/plugins/Engram/Engram.dll, so the game
        // directory is four levels up. Inside the game there is nothing to search for.
        wchar_t modulePath[MAX_PATH] = {};
        HMODULE self = nullptr;
        GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |
                               GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                           reinterpret_cast<LPCWSTR>(&Log), &self);
        if (self && GetModuleFileNameW(self, modulePath, MAX_PATH))
        {
            engram::SetGameDir(
                std::filesystem::path(modulePath).parent_path().parent_path().parent_path().parent_path());
        }

        engram::SetLogger([](const std::string& message) { Log(message); });

        auto* rtti = RED4ext::CRTTISystem::Get();
        rtti->AddRegisterCallback(RegisterTypes);
        rtti->AddPostRegisterCallback(PostRegisterTypes);

        Log("Engram " + std::string(engram::kVersion) + " loading");
        break;
    }
    case RED4ext::v1::EMainReason::Unload:
    {
        g_sdk = nullptr;
        g_handle = nullptr;
        break;
    }
    }

    return true;
}

RED4EXT_C_EXPORT void RED4EXT_CALL Query(RED4ext::v1::PluginInfo* aInfo)
{
    aInfo->name = L"Engram";
    aInfo->author = L"tfthushaar";
    aInfo->version = RED4EXT_V1_SEMVER(1, 0, 0);
        // Pinned to the build the SDK submodule describes. RED4ext refuses to load a plugin
    // built against a different game build, which is the behaviour we want: an SDK that
    // disagrees with the game about struct layouts would fail far less politely.
    aInfo->runtime = RED4EXT_V1_RUNTIME_VERSION_LATEST;
    aInfo->sdk = RED4EXT_V1_SDK_VERSION_CURRENT;
}

RED4EXT_C_EXPORT uint32_t RED4EXT_CALL Supports()
{
    return RED4EXT_API_VERSION_1;
}
