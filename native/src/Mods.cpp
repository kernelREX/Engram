#include "Mods.hpp"

#include <algorithm>
#include <fstream>
#include <map>
#include <regex>
#include <set>
#include <sstream>

#include <nlohmann/json.hpp>

#include <windows.h>

#pragma comment(lib, "version.lib")

using json = nlohmann::json;

namespace
{
const std::set<std::string> kIgnored = {
    "__folder_managed_by_vortex", "__folder_managed_by_vortex.txt", "desktop.ini",
    "thumbs.db", ".git", ".gitkeep", "engram.json"};

// Anything matching this in a redscript source means the mod keeps state in the save.
const std::regex kPersistent(R"(\bpersistent\s+(?:let|func)\b)");

// A version at the end of a folder name, the way Vortex and Nexus tend to leave it.
const std::regex kNameVersion(R"(^(.*?)[ _\-]+v?(\d+(?:\.\d+)*[a-z]?)$)");

// A version a Lua mod assigns to itself.
// The boundary matters: without it this matches inside a longer identifier such as
// `nativeSettingsVersion`, picks a different number than the Python does, and the two
// halves then disagree about a mod's version for no real reason.
const std::regex kLuaVersion(
    R"((?:^|[^A-Za-z])(?:mod|Mod)?[Vv]ersion\s*=\s*['"]([0-9][^'"]{0,19})['"])");

bool Interesting(const std::filesystem::path& aPath)
{
    const auto name = aPath.filename().string();
    return kIgnored.find(name) == kIgnored.end() && !name.empty() && name[0] != '.';
}

std::vector<std::filesystem::path> Children(const std::filesystem::path& aRoot)
{
    std::vector<std::filesystem::path> out;
    std::error_code error;
    if (!std::filesystem::is_directory(aRoot, error) || error)
    {
        return out;
    }
    for (const auto& entry : std::filesystem::directory_iterator(aRoot, error))
    {
        if (error)
        {
            break;
        }
        if (Interesting(entry.path()))
        {
            out.push_back(entry.path());
        }
    }
    std::sort(out.begin(), out.end());
    return out;
}

std::string ReadText(const std::filesystem::path& aPath, size_t aLimit = 2000000)
{
    std::ifstream file(aPath, std::ios::binary);
    if (!file)
    {
        return {};
    }
    std::string out((std::istreambuf_iterator<char>(file)), std::istreambuf_iterator<char>());
    if (out.size() > aLimit)
    {
        out.resize(aLimit);
    }
    return out;
}

std::vector<std::filesystem::path> SourcesUnder(const std::filesystem::path& aFolder,
                                                const std::vector<std::string>& aSuffixes,
                                                size_t aCap = 400)
{
    std::vector<std::filesystem::path> out;
    std::error_code error;
    for (const auto& entry : std::filesystem::recursive_directory_iterator(aFolder, error))
    {
        if (error || out.size() >= aCap)
        {
            break;
        }
        if (!entry.is_regular_file(error) || error)
        {
            continue;
        }
        auto extension = entry.path().extension().string();
        std::transform(extension.begin(), extension.end(), extension.begin(), ::tolower);
        if (std::find(aSuffixes.begin(), aSuffixes.end(), extension) != aSuffixes.end())
        {
            out.push_back(entry.path());
        }
    }
    // Sorted, because the Python walks these in sorted order and the first version match
    // wins. An unsorted walk here would pick a different one and look like a version
    // mismatch between somebody using the mod and somebody using the tool.
    std::sort(out.begin(), out.end());
    return out;
}

std::pair<std::string, std::string> SplitVersion(const std::string& aName)
{
    std::smatch match;
    if (std::regex_match(aName, match, kNameVersion) && match[1].length() > 0)
    {
        return {match[1].str(), match[2].str()};
    }
    return {aName, {}};
}

std::string VersionFile(const std::filesystem::path& aFolder)
{
    for (const char* name : {".version", "version.txt", "VERSION"})
    {
        std::error_code error;
        if (!std::filesystem::is_regular_file(aFolder / name, error) || error)
        {
            continue;
        }
        std::string text = ReadText(aFolder / name, 256);
        const auto end = text.find_first_of("\r\n");
        if (end != std::string::npos)
        {
            text = text.substr(0, end);
        }
        while (!text.empty() && std::isspace(static_cast<unsigned char>(text.back())))
        {
            text.pop_back();
        }
        if (!text.empty() && text.size() <= 40)
        {
            return text;
        }
    }
    return {};
}

// A DLL's own version resource, which is the only reliable way to tell two builds of a
// native plugin apart.
std::string DllVersion(const std::filesystem::path& aPath)
{
    DWORD handle = 0;
    const DWORD size = GetFileVersionInfoSizeW(aPath.c_str(), &handle);
    if (size == 0)
    {
        return {};
    }

    std::vector<uint8_t> block(size);
    if (!GetFileVersionInfoW(aPath.c_str(), 0, size, block.data()))
    {
        return {};
    }

    struct LangAndPage
    {
        WORD language;
        WORD codePage;
    };

    LangAndPage* translations = nullptr;
    UINT translationBytes = 0;
    if (!VerQueryValueW(block.data(), L"\\VarFileInfo\\Translation",
                        reinterpret_cast<LPVOID*>(&translations), &translationBytes) ||
        translationBytes < sizeof(LangAndPage))
    {
        return {};
    }

    for (const char* field : {"ProductVersion", "FileVersion"})
    {
        wchar_t query[128];
        swprintf_s(query, L"\\StringFileInfo\\%04x%04x\\%hs", translations[0].language,
                   translations[0].codePage, field);

        wchar_t* value = nullptr;
        UINT valueLength = 0;
        if (VerQueryValueW(block.data(), query, reinterpret_cast<LPVOID*>(&value),
                           &valueLength) &&
            value && valueLength > 1)
        {
            const int needed =
                WideCharToMultiByte(CP_UTF8, 0, value, -1, nullptr, 0, nullptr, nullptr);
            std::string out(static_cast<size_t>(needed > 0 ? needed - 1 : 0), '\0');
            WideCharToMultiByte(CP_UTF8, 0, value, -1, out.data(), needed, nullptr, nullptr);
            while (!out.empty() && std::isspace(static_cast<unsigned char>(out.back())))
            {
                out.pop_back();
            }
            if (!out.empty())
            {
                return out;
            }
        }
    }
    return {};
}

// The convention a mod author can use to settle all of this properly.
void ApplyDeclaration(const std::filesystem::path& aFolder, engram::ModEntry& aEntry)
{
    std::error_code error;
    const auto path = aFolder / "engram.json";
    if (!std::filesystem::is_regular_file(path, error) || error)
    {
        return;
    }
    try
    {
        const json declared = json::parse(ReadText(path, 64 * 1024));
        if (!declared.is_object())
        {
            return;
        }
        aEntry.name = declared.value("name", aEntry.name);
        aEntry.version = declared.value("version", aEntry.version);
        if (declared.contains("writesPersistentState"))
        {
            aEntry.writesPersistentState = declared["writesPersistentState"].get<bool>();
            aEntry.persistentKnown = true;
        }
        aEntry.declared = true;
    }
    catch (const std::exception&)
    {
    }
}

std::string ArchiveBase(const std::string& aName)
{
    std::string lowered = aName;
    std::transform(lowered.begin(), lowered.end(), lowered.begin(), ::tolower);
    for (const char* suffix : {".archive.xl", ".archive", ".xl"})
    {
        const size_t length = std::strlen(suffix);
        if (lowered.size() > length && lowered.compare(lowered.size() - length, length, suffix) == 0)
        {
            return aName.substr(0, aName.size() - length);
        }
    }
    return aName;
}
} // namespace

namespace engram
{
std::string NormaliseName(const std::string& aName)
{
    const auto [base, version] = SplitVersion(aName);
    std::string out;
    for (const char character : base)
    {
        if (std::isalnum(static_cast<unsigned char>(character)))
        {
            out.push_back(static_cast<char>(std::tolower(static_cast<unsigned char>(character))));
        }
    }
    return out;
}

std::string ModEntry::Key() const
{
    return kind + ":" + NormaliseName(name);
}

std::string ModEntry::Label() const
{
    std::string out = name + " (" + kind;
    if (!version.empty())
    {
        out += ", " + version;
    }
    return out + ")";
}

bool ModSet::HasFramework(const std::string& aNormalisedName) const
{
    for (const auto& entry : entries)
    {
        if (NormaliseName(entry.name) == aNormalisedName)
        {
            return true;
        }
    }
    return false;
}

std::vector<ModEntry> ModSet::OfKind(const std::string& aKind) const
{
    std::vector<ModEntry> out;
    for (const auto& entry : entries)
    {
        if (entry.kind == aKind)
        {
            out.push_back(entry);
        }
    }
    return out;
}

ModSet ScanMods(const std::filesystem::path& aGameDir)
{
    ModSet set;
    std::error_code error;
    set.phantomLiberty =
        std::filesystem::is_directory(aGameDir / "archive" / "pc" / "ep1", error) && !error;

    // r6/scripts: redscript mods, the ones that can hold save state.
    for (const auto& child : Children(aGameDir / "r6" / "scripts"))
    {
        if (!std::filesystem::is_directory(child, error) || error)
        {
            continue;
        }
        ModEntry entry;
        entry.name = child.filename().string();
        entry.kind = "redscript";
        const auto [base, nameVersion] = SplitVersion(entry.name);
        entry.version = VersionFile(child);
        if (entry.version.empty())
        {
            entry.version = nameVersion;
        }

        std::string sources;
        for (const auto& source : SourcesUnder(child, {".reds", ".script"}))
        {
            sources += ReadText(source, 200000);
            sources.push_back('\n');
        }
        entry.writesPersistentState = std::regex_search(sources, kPersistent);
        entry.persistentKnown = true;

        ApplyDeclaration(child, entry);
        set.entries.push_back(entry);
    }

    // red4ext/plugins: native plugins, versioned by their own DLL resource.
    for (const auto& child : Children(aGameDir / "red4ext" / "plugins"))
    {
        if (!std::filesystem::is_directory(child, error) || error)
        {
            continue;
        }
        const auto dlls = SourcesUnder(child, {".dll"}, 32);
        if (dlls.empty())
        {
            continue;
        }

        ModEntry entry;
        entry.name = child.filename().string();
        entry.kind = "red4ext";

        auto chosen = dlls.front();
        for (const auto& dll : dlls)
        {
            if (NormaliseName(dll.stem().string()) == NormaliseName(entry.name))
            {
                chosen = dll;
                break;
            }
        }
        entry.version = DllVersion(chosen);
        if (entry.version.empty())
        {
            entry.version = VersionFile(child);
        }
        if (entry.version.empty())
        {
            entry.version = SplitVersion(entry.name).second;
        }
        entry.extendsRecords = !SourcesUnder(child, {".xl", ".archive"}, 4).empty();

        ApplyDeclaration(child, entry);
        set.entries.push_back(entry);
    }

    // archive/pc/mod: resource archives, and the ArchiveXL files that extend records.
    {
        std::map<std::string, bool> groups;
        for (const auto& child : Children(aGameDir / "archive" / "pc" / "mod"))
        {
            if (std::filesystem::is_directory(child, error))
            {
                continue;
            }
            std::string lowered = child.filename().string();
            std::transform(lowered.begin(), lowered.end(), lowered.begin(), ::tolower);
            const bool isArchive = lowered.size() > 8 &&
                                   lowered.compare(lowered.size() - 8, 8, ".archive") == 0;
            const bool isXl =
                lowered.size() > 3 && lowered.compare(lowered.size() - 3, 3, ".xl") == 0;
            if (!isArchive && !isXl)
            {
                continue;
            }
            const auto base = ArchiveBase(child.filename().string());
            groups[base] = groups[base] || isXl;
        }
        for (const auto& [base, hasXl] : groups)
        {
            ModEntry entry;
            entry.name = base;
            entry.kind = "archive";
            entry.extendsRecords = hasXl;
            entry.persistentKnown = true;
            set.entries.push_back(entry);
        }
    }

    // r6/tweaks: TweakXL records, which inventory items can point at.
    for (const auto& child : Children(aGameDir / "r6" / "tweaks"))
    {
        ModEntry entry;
        entry.kind = "tweak";
        entry.extendsRecords = true;
        entry.persistentKnown = true;
        if (std::filesystem::is_directory(child, error) && !error)
        {
            entry.name = child.filename().string();
            entry.version = VersionFile(child);
            if (entry.version.empty())
            {
                entry.version = SplitVersion(entry.name).second;
            }
            ApplyDeclaration(child, entry);
        }
        else
        {
            auto extension = child.extension().string();
            std::transform(extension.begin(), extension.end(), extension.begin(), ::tolower);
            if (extension != ".yaml" && extension != ".yml" && extension != ".json")
            {
                continue;
            }
            entry.name = child.stem().string();
        }
        set.entries.push_back(entry);
    }

    // mods: REDmod packages, which publish a name and a version in info.json.
    for (const auto& child : Children(aGameDir / "mods"))
    {
        if (!std::filesystem::is_directory(child, error) || error)
        {
            continue;
        }
        ModEntry entry;
        entry.name = child.filename().string();
        entry.kind = "redmod";
        try
        {
            const auto text = ReadText(child / "info.json", 64 * 1024);
            if (!text.empty())
            {
                const json info = json::parse(text);
                entry.name = info.value("name", entry.name);
                entry.version = info.value("version", std::string());
            }
        }
        catch (const std::exception&)
        {
        }
        if (entry.version.empty())
        {
            entry.version = SplitVersion(child.filename().string()).second;
        }
        entry.extendsRecords = !SourcesUnder(child, {".archive"}, 4).empty();
        ApplyDeclaration(child, entry);
        set.entries.push_back(entry);
    }

    // CET mods, which keep their own state in their own folder rather than the save.
    const auto cet =
        aGameDir / "bin" / "x64" / "plugins" / "cyber_engine_tweaks" / "mods";
    for (const auto& child : Children(cet))
    {
        if (!std::filesystem::is_directory(child, error) || error)
        {
            continue;
        }
        ModEntry entry;
        entry.name = child.filename().string();
        entry.kind = "cet";
        entry.persistentKnown = true;
        entry.version = VersionFile(child);
        if (entry.version.empty())
        {
            std::string lua;
            for (const auto& source : SourcesUnder(child, {".lua"}, 40))
            {
                lua += ReadText(source, 200000);
                lua.push_back('\n');
            }
            std::smatch match;
            if (std::regex_search(lua, match, kLuaVersion))
            {
                entry.version = match[1].str();
            }
        }
        if (entry.version.empty())
        {
            entry.version = SplitVersion(entry.name).second;
        }
        ApplyDeclaration(child, entry);
        set.entries.push_back(entry);
    }

    std::sort(set.entries.begin(), set.entries.end(),
              [](const ModEntry& aLeft, const ModEntry& aRight)
              {
                  if (aLeft.kind != aRight.kind)
                  {
                      return aLeft.kind < aRight.kind;
                  }
                  return NormaliseName(aLeft.name) < NormaliseName(aRight.name);
              });
    return set;
}

std::string ModsToJson(const ModSet& aMods)
{
    json out = json::array();
    for (const auto& entry : aMods.entries)
    {
        json item;
        item["name"] = entry.name;
        item["kind"] = entry.kind;
        if (!entry.version.empty())
        {
            item["version"] = entry.version;
        }
        if (entry.persistentKnown)
        {
            item["writesPersistentState"] = entry.writesPersistentState;
        }
        if (entry.declared)
        {
            item["declared"] = true;
        }
        if (entry.extendsRecords)
        {
            item["extendsRecords"] = true;
        }
        out.push_back(item);
    }
    return out.dump();
}

ModSet ModsFromJson(const std::string& aJson)
{
    ModSet set;
    try
    {
        const json parsed = json::parse(aJson);
        const json& list = parsed.is_array() ? parsed : parsed.value("mods", json::array());
        if (parsed.is_object())
        {
            set.phantomLiberty = parsed.value("phantomLiberty", false);
        }
        for (const auto& item : list)
        {
            ModEntry entry;
            entry.name = item.value("name", std::string("unnamed"));
            entry.kind = item.value("kind", std::string("unknown"));
            entry.version = item.value("version", std::string());
            if (item.contains("writesPersistentState"))
            {
                entry.writesPersistentState = item["writesPersistentState"].get<bool>();
                entry.persistentKnown = true;
            }
            entry.declared = item.value("declared", false);
            entry.extendsRecords = item.value("extendsRecords", false);
            set.entries.push_back(entry);
        }
    }
    catch (const std::exception&)
    {
    }
    return set;
}

bool CheckReport::Blocked() const
{
    return CountOf(Severity::Block) > 0;
}

int CheckReport::CountOf(Severity aSeverity) const
{
    int count = 0;
    for (const auto& finding : findings)
    {
        if (finding.severity == aSeverity)
        {
            ++count;
        }
    }
    return count;
}

std::string CheckReport::Summarise() const
{
    const int blocks = CountOf(Severity::Block);
    const int warnings = CountOf(Severity::Warn);
    const int notes = CountOf(Severity::Note);
    if (blocks)
    {
        return std::to_string(blocks) + " thing(s) stop this save loading here";
    }
    if (warnings)
    {
        return "This save should load, with " + std::to_string(warnings) +
               " warning(s) worth reading";
    }
    if (notes)
    {
        return "This save should load cleanly, " + std::to_string(notes) + " note(s)";
    }
    return "This save should load cleanly";
}

std::vector<std::string> CheckReport::Lines() const
{
    std::vector<Finding> sorted = findings;
    std::stable_sort(sorted.begin(), sorted.end(),
                     [](const Finding& aLeft, const Finding& aRight)
                     { return static_cast<int>(aLeft.severity) > static_cast<int>(aRight.severity); });

    std::vector<std::string> out;
    for (const auto& finding : sorted)
    {
        std::ostringstream line;
        line << static_cast<int>(finding.severity) << '\t' << finding.summary << '\t'
             << finding.detail << '\t';
        for (size_t i = 0; i < finding.items.size(); ++i)
        {
            if (i)
            {
                line << " | ";
            }
            line << finding.items[i];
        }
        out.push_back(line.str());
    }
    return out;
}

Finding ModsOnThisSave(const ModSet& aMods)
{
    Finding finding;
    finding.code = "save-has-mods";

    if (aMods.entries.empty())
    {
        finding.severity = Severity::Note;
        finding.summary = "This save was made with no mods installed";
        finding.detail =
            "Nothing from a mod is inside it, so it will load on any machine running the "
            "same patch.";
        return finding;
    }

    finding.severity = Severity::Warn;
    finding.summary = "This save was made with " + std::to_string(aMods.entries.size()) +
                      " mod(s) installed";
    finding.detail =
        "A modded save carries those mods' state inside sav.dat. Anyone loading it without "
        "them gets a save that may behave differently, and the game disables achievements "
        "for it. The full list is below.";

    for (const auto& entry : aMods.entries)
    {
        std::string line = entry.Label();
        if (entry.writesPersistentState)
        {
            line += "  [keeps state in the save]";
        }
        else if (entry.extendsRecords)
        {
            line += "  [adds records]";
        }
        finding.items.push_back(line);
    }
    return finding;
}

CheckReport BuildReport(const std::string& aSaveJson, const ModSet& aSender,
                   const ModSet& aReceiver, int aReceiverGameVersion, bool aGameRunning,
                   bool aSteamRunning)
{
    CheckReport report;
    const auto add = [&report](Severity aSeverity, const char* aCode, std::string aSummary,
                               std::string aDetail, std::vector<std::string> aItems = {})
    {
        report.findings.push_back(
            Finding{aSeverity, aCode, std::move(aSummary), std::move(aDetail), std::move(aItems)});
    };

    json save = json::object();
    try
    {
        save = json::parse(aSaveJson);
    }
    catch (const std::exception&)
    {
    }

    // The save itself.
    const int senderVersion = save.value("gameVersion", 0);
    const std::string build = save.value("buildPatch", std::string("unknown"));

    if (senderVersion && aReceiverGameVersion)
    {
        if (senderVersion > aReceiverGameVersion)
        {
            add(Severity::Block, "downgrade",
                "This save is from game " + build + " and yours is older",
                "Cyberpunk does not read a save from a newer patch. Update the game and "
                "try again.");
        }
        else if (senderVersion < aReceiverGameVersion)
        {
            add(Severity::Note, "older-save",
                "This save is from game " + build + ", which is older than yours",
                "Loading an older save on a newer patch is normal and the game upgrades it "
                "in place.");
        }
    }
    else if (senderVersion)
    {
        add(Severity::Note, "no-local-version",
            "Cannot compare game versions, because there are no saves here yet",
            "The save is from game " + build + ". If your game is older, it will not load.");
    }

    bool needsPhantomLiberty = false;
    if (save.contains("additionalContentIds"))
    {
        for (const auto& id : save["additionalContentIds"])
        {
            if (id.is_string() && id.get<std::string>() == "EP1")
            {
                needsPhantomLiberty = true;
            }
        }
    }
    if (needsPhantomLiberty && !aReceiver.phantomLiberty)
    {
        add(Severity::Block, "missing-phantom-liberty",
            "This save needs Phantom Liberty and it is not installed",
            "The save was made with the expansion active. Without it the game has nothing "
            "to load the expansion's content from.");
    }

    // The alert about what the save was made with, which the receiver sees every time.
    report.findings.push_back(ModsOnThisSave(aSender));

    if (save.value("isModded", false))
    {
        add(Severity::Note, "modded-flag", "The game has flagged this save as modded",
            "Achievements stay disabled while playing it, and the load menu marks it. That "
            "flag is the game's own and Engram does not set or clear it.");
    }

    // The two mod lists, compared.
    std::map<std::string, ModEntry> mine;
    std::map<std::string, ModEntry> theirs;
    for (const auto& entry : aReceiver.entries)
    {
        mine[entry.Key()] = entry;
    }
    for (const auto& entry : aSender.entries)
    {
        theirs[entry.Key()] = entry;
    }

    std::vector<std::string> missingRecords;
    std::vector<std::string> missingRedscript;
    std::vector<std::string> missingOther;
    std::vector<std::string> persistentMismatch;
    std::vector<std::string> versionMismatch;
    std::vector<std::string> unknownVersions;

    for (const auto& [key, entry] : theirs)
    {
        const auto found = mine.find(key);
        if (found == mine.end())
        {
            if (entry.extendsRecords)
            {
                missingRecords.push_back(entry.Label());
            }
            else if (entry.kind == "redscript")
            {
                missingRedscript.push_back(entry.Label());
            }
            else
            {
                missingOther.push_back(entry.Label());
            }
            continue;
        }

        const ModEntry& here = found->second;
        const bool bothVersioned = !entry.version.empty() && !here.version.empty();
        if (bothVersioned && entry.version != here.version)
        {
            const std::string line = entry.name + ": they have " + entry.version +
                                     ", you have " + here.version;
            if (entry.writesPersistentState || here.writesPersistentState)
            {
                persistentMismatch.push_back(line);
            }
            else
            {
                versionMismatch.push_back(line);
            }
        }
        else if (!bothVersioned &&
                 (entry.writesPersistentState || here.writesPersistentState))
        {
            unknownVersions.push_back(entry.name);
        }
    }

    std::vector<std::string> extra;
    for (const auto& [key, entry] : mine)
    {
        if (theirs.find(key) == theirs.end())
        {
            extra.push_back(entry.Label());
        }
    }

    if (!missingRecords.empty())
    {
        add(Severity::Block, "missing-records",
            std::to_string(missingRecords.size()) +
                " mod(s) that add records are not installed here",
            "The save can refer to items, vehicles and clothing from these by record name. "
            "Those names will not resolve on this machine, which is the failure most likely "
            "to stop the save loading at all.",
            missingRecords);
    }

    for (const char* framework : {"archivexl", "tweakxl"})
    {
        if (aSender.HasFramework(framework) && !aReceiver.HasFramework(framework))
        {
            const std::string proper =
                std::string(framework) == "archivexl" ? "ArchiveXL" : "TweakXL";
            add(Severity::Block, "missing-framework",
                proper + " is not installed here, and the sender has it",
                proper + " is what resolves the extra records a modded save refers to. "
                         "Without it, anything those mods added is a dangling reference.");
        }
    }

    if (!persistentMismatch.empty())
    {
        add(Severity::Warn, "persistent-version",
            std::to_string(persistentMismatch.size()) +
                " mod(s) that keep state in the save are a different version here",
            "Read this one. If the mod changed its persistent fields between these two "
            "versions, the game drops that mod's data when the save loads. Nothing fails, "
            "nothing is reported, and everything the mod was tracking is gone.",
            persistentMismatch);
    }

    if (!missingRedscript.empty())
    {
        add(Severity::Warn, "missing-redscript",
            std::to_string(missingRedscript.size()) +
                " redscript mod(s) the sender has are missing here",
            "Their state is in the save and nothing will read it. Usually harmless, and it "
            "comes back if you install the mod later.",
            missingRedscript);
    }

    if (!versionMismatch.empty())
    {
        add(Severity::Note, "version-differs",
            std::to_string(versionMismatch.size()) + " mod(s) are a different version here",
            "None of these declare state in the save, so the difference is cosmetic as far "
            "as the save is concerned.",
            versionMismatch);
    }

    if (!unknownVersions.empty())
    {
        add(Severity::Note, "version-unknown",
            std::to_string(unknownVersions.size()) +
                " mod(s) keep state in the save but publish no version",
            "Engram cannot tell whether these match.", unknownVersions);
    }

    if (!missingOther.empty())
    {
        add(Severity::Note, "missing-other",
            std::to_string(missingOther.size()) +
                " other mod(s) the sender has are missing here",
            "", missingOther);
    }

    if (!extra.empty())
    {
        add(Severity::Note, "extra-here",
            "You have " + std::to_string(extra.size()) + " mod(s) the sender does not",
            "These were not active when the save was made. They apply from now on.", extra);
    }

    // What is holding the save folder open right now.
    if (aGameRunning)
    {
        add(Severity::Block, "game-running", "Cyberpunk is open",
            "The game writes its own saves over this folder and will not see a new one that "
            "appears while it is running.");
    }
    if (aSteamRunning)
    {
        add(Severity::Warn, "steam-running",
            "Steam is running, and Steam Cloud syncs this folder",
            "Steam can replace an imported save with its cloud copy within seconds of the "
            "import working, which looks exactly like the import having failed. Close Steam, "
            "import, then start Steam again.");
    }

    return report;
}
} // namespace engram
