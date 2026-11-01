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

#include <RED4ext/RED4ext.hpp>
#include <RED4ext/RTTITypes.hpp>
#include <RED4ext/Scripting/IScriptable.hpp>

#include <filesystem>
#include <string>
#include <vector>

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
    aInfo->version = RED4EXT_V1_SEMVER(0, 1, 0);
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
