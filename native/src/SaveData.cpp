#include "SaveData.hpp"

#include <algorithm>
#include <fstream>
#include <regex>
#include <stdexcept>

#include <nlohmann/json.hpp>

using json = nlohmann::json;

namespace
{
constexpr const char* kSav = "sav.dat";
constexpr const char* kScreenshot = "screenshot.png";
constexpr const char* kEnabledMods = "EnabledMods.json";
constexpr const char* kPartialSuffix = ".engram-incoming";

// The metadata file carries a version in its name, metadata.9.json today, so it is found
// by shape rather than by that exact name.
std::filesystem::path MetadataPath(const std::filesystem::path& aFolder)
{
    std::error_code error;
    for (const auto& entry : std::filesystem::directory_iterator(aFolder, error))
    {
        if (error)
        {
            break;
        }
        const auto name = entry.path().filename().string();
        if (name.rfind("metadata", 0) == 0 && entry.path().extension() == ".json")
        {
            return entry.path();
        }
    }
    return {};
}

engram::Bytes ReadWholeFile(const std::filesystem::path& aPath)
{
    std::ifstream file(aPath, std::ios::binary);
    if (!file)
    {
        throw std::runtime_error("could not read " + aPath.filename().string());
    }
    return engram::Bytes((std::istreambuf_iterator<char>(file)),
                         std::istreambuf_iterator<char>());
}

json MetadataBlock(const json& aDocument)
{
    if (!aDocument.contains("Data") || !aDocument["Data"].contains("metadata"))
    {
        throw std::runtime_error("the metadata file has no Data.metadata block");
    }
    return aDocument["Data"]["metadata"];
}

uint64_t FolderSize(const std::filesystem::path& aFolder)
{
    uint64_t total = 0;
    std::error_code error;
    for (const auto& entry : std::filesystem::directory_iterator(aFolder, error))
    {
        if (error)
        {
            break;
        }
        if (entry.is_regular_file(error) && !error)
        {
            total += entry.file_size(error);
        }
    }
    return total;
}
} // namespace

namespace engram
{
std::string SaveInfo::Describe() const
{
    const int minutes = static_cast<int>(playTime) / 60;
    const int hours = minutes / 60;
    const int rest = minutes % 60;

    std::string out = "level " + std::to_string(level) + " " + lifePath + ", " +
                      std::to_string(hours) + "h ";
    if (rest < 10)
    {
        out += "0";
    }
    out += std::to_string(rest) + "m played";
    if (!timestampString.empty())
    {
        out += ", " + timestampString;
    }
    return out;
}

SaveInfo ReadSave(const std::filesystem::path& aFolder)
{
    const auto metadata = MetadataPath(aFolder);
    if (metadata.empty())
    {
        throw std::runtime_error(aFolder.filename().string() + " has no metadata file");
    }

    const auto raw = ReadWholeFile(metadata);
    json document;
    try
    {
        document = json::parse(std::string(raw.begin(), raw.end()));
    }
    catch (const std::exception&)
    {
        throw std::runtime_error("could not read " + metadata.filename().string());
    }

    const json block = MetadataBlock(document);
    SaveInfo info;
    info.folderName = aFolder.filename().string();
    info.name = block.value("name", info.folderName);
    info.buildPatch = block.value("buildPatch", std::string());
    info.lifePath = block.value("lifePath", std::string("unknown"));
    info.difficulty = block.value("difficulty", std::string());
    info.timestampString = block.value("timestampString", std::string());
    info.level = static_cast<int>(block.value("level", 0.0));
    info.streetCred = static_cast<int>(block.value("streetCred", 0.0));
    info.gameVersion = block.value("gameVersion", 0);
    info.saveVersion = block.value("saveVersion", 0);
    info.playTime = block.value("playTime", 0.0);
    info.isModded = block.value("isModded", false);
    info.sizeBytes = FolderSize(aFolder);

    // The game's own test, from SaveMetadataInfo.IsEp1Save in the script source.
    if (block.contains("additionalContentIds"))
    {
        for (const auto& id : block["additionalContentIds"])
        {
            if (id.is_string() && id.get<std::string>() == "EP1")
            {
                info.needsPhantomLiberty = true;
            }
        }
    }
    return info;
}

std::vector<SaveInfo> ListSaves(const std::filesystem::path& aRoot)
{
    const auto names = ListSaveFolders(aRoot);
    std::vector<SaveInfo> out;
    out.reserve(names.size());
    for (const auto& name : names)
    {
        try
        {
            out.push_back(ReadSave(aRoot / name));
        }
        catch (const std::exception&)
        {
            // A save that cannot be read is skipped rather than failing the whole list.
        }
    }
    return out;
}

Files CollectSave(const std::filesystem::path& aFolder)
{
    const auto metadata = MetadataPath(aFolder);
    if (metadata.empty())
    {
        throw std::runtime_error(aFolder.filename().string() + " has no metadata file to pack");
    }

    Files files;
    files[metadata.filename().string()] = ReadWholeFile(metadata);
    files[kSav] = ReadWholeFile(aFolder / kSav);

    std::error_code error;
    if (std::filesystem::exists(aFolder / kScreenshot, error) && !error)
    {
        files[kScreenshot] = ReadWholeFile(aFolder / kScreenshot);
    }
    return files;
}

std::string SaveMetadataJson(const std::filesystem::path& aFolder)
{
    const auto metadata = MetadataPath(aFolder);
    if (metadata.empty())
    {
        return "{}";
    }
    const auto raw = ReadWholeFile(metadata);
    return std::string(raw.begin(), raw.end());
}

std::string FreeSlotName(const std::filesystem::path& aRoot, const std::string& aPrefix)
{
    for (int index = 1; index < 10000; ++index)
    {
        const std::string candidate = aPrefix + "-" + std::to_string(index);
        std::error_code error;
        if (!std::filesystem::exists(aRoot / candidate, error))
        {
            return candidate;
        }
    }
    throw std::runtime_error("could not find a free save slot name");
}

namespace
{
// The load menu shows the metadata's own name, not the folder, so leaving it alone would
// list the sender's slot name on the receiver's machine.
Bytes Retitle(const Bytes& aMetadata, const std::string& aSlotName)
{
    try
    {
        json document = json::parse(std::string(aMetadata.begin(), aMetadata.end()));
        document["Data"]["metadata"]["name"] = aSlotName;
        const std::string text = document.dump(4);
        return Bytes(text.begin(), text.end());
    }
    catch (const std::exception&)
    {
        return aMetadata;
    }
}
} // namespace

std::filesystem::path InstallSave(const std::filesystem::path& aRoot,
                                  const std::string& aSlotName, const Files& aFiles)
{
    if (aFiles.find(kSav) == aFiles.end())
    {
        throw std::runtime_error("an incoming save must contain sav.dat");
    }

    std::error_code error;
    std::filesystem::create_directories(aRoot, error);

    const auto staging = aRoot / (aSlotName + kPartialSuffix);
    const auto final = aRoot / aSlotName;

    if (std::filesystem::exists(final, error))
    {
        throw std::runtime_error(aSlotName + " already exists, and Engram does not overwrite saves");
    }
    std::filesystem::remove_all(staging, error);

    try
    {
        std::filesystem::create_directories(staging);
        for (const auto& [name, data] : aFiles)
        {
            // Shared by every save, carries no playthrough state, never copied.
            if (name == kEnabledMods)
            {
                continue;
            }
            if (name.find('/') != std::string::npos || name.find('\\') != std::string::npos)
            {
                throw std::runtime_error(name + " is not a plain file name");
            }

            const bool isMetadata = name.rfind("metadata", 0) == 0;
            const Bytes& payload = data;
            const Bytes written = isMetadata ? Retitle(payload, aSlotName) : payload;

            std::ofstream file((staging / name).string(), std::ios::binary);
            if (!file)
            {
                throw std::runtime_error("could not write " + name);
            }
            file.write(reinterpret_cast<const char*>(written.data()),
                       static_cast<std::streamsize>(written.size()));
            if (!file)
            {
                throw std::runtime_error("could not finish writing " + name);
            }
        }
        std::filesystem::rename(staging, final);
    }
    catch (...)
    {
        std::filesystem::remove_all(staging, error);
        throw;
    }
    return final;
}

int LocalGameVersion(const std::filesystem::path& aRoot)
{
    int highest = 0;
    for (const auto& save : ListSaves(aRoot))
    {
        highest = std::max(highest, save.gameVersion);
    }
    return highest;
}
} // namespace engram
