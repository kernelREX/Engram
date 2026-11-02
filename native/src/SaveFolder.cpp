#include "SaveFolder.hpp"

#include <algorithm>
#include <system_error>

#include <windows.h>

#include <knownfolders.h>
#include <shlobj.h>

namespace
{
constexpr const wchar_t* kSaveSubPath = L"CD Projekt Red\\Cyberpunk 2077";

// A folder is a save when it holds the save itself and something describing it. The
// metadata file carries a version in its name, metadata.9.json today, so it is matched by
// shape rather than by that exact name.
bool LooksLikeASave(const std::filesystem::path& aFolder)
{
    std::error_code error;
    if (!std::filesystem::exists(aFolder / "sav.dat", error) || error)
    {
        return false;
    }

    for (const auto& entry : std::filesystem::directory_iterator(aFolder, error))
    {
        if (error)
        {
            return false;
        }
        const auto name = entry.path().filename().string();
        if (name.rfind("metadata", 0) == 0 && entry.path().extension() == ".json")
        {
            return true;
        }
    }
    return false;
}

std::filesystem::file_time_type WrittenAt(const std::filesystem::path& aFolder)
{
    std::error_code error;
    const auto when = std::filesystem::last_write_time(aFolder / "sav.dat", error);
    return error ? std::filesystem::file_time_type::min() : when;
}
} // namespace

namespace engram
{
std::filesystem::path SaveFolder()
{
    PWSTR raw = nullptr;
    const auto result = SHGetKnownFolderPath(FOLDERID_SavedGames, 0, nullptr, &raw);
    if (FAILED(result) || raw == nullptr)
    {
        if (raw != nullptr)
        {
            CoTaskMemFree(raw);
        }
        throw std::runtime_error("Windows would not say where Saved Games is");
    }

    std::filesystem::path root(raw);
    CoTaskMemFree(raw);
    return root / kSaveSubPath;
}

std::filesystem::path FileFolder()
{
    return SaveFolder().parent_path().parent_path() / "Engram";
}

std::vector<std::string> ListSaveFolders(const std::filesystem::path& aRoot)
{
    std::error_code error;
    if (!std::filesystem::is_directory(aRoot, error) || error)
    {
        return {};
    }

    std::vector<std::pair<std::filesystem::file_time_type, std::string>> found;
    for (const auto& entry : std::filesystem::directory_iterator(aRoot, error))
    {
        if (error)
        {
            break;
        }
        if (!entry.is_directory(error) || error)
        {
            continue;
        }
        if (!LooksLikeASave(entry.path()))
        {
            continue;
        }
        found.emplace_back(WrittenAt(entry.path()), entry.path().filename().string());
    }

    std::sort(found.begin(), found.end(),
              [](const auto& aLeft, const auto& aRight) { return aLeft.first > aRight.first; });

    std::vector<std::string> names;
    names.reserve(found.size());
    for (auto& [when, name] : found)
    {
        names.push_back(std::move(name));
    }
    return names;
}
} // namespace engram
