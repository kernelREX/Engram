#pragma once

#include <filesystem>
#include <string>
#include <vector>

#include "Container.hpp"
#include "SaveFolder.hpp"
#include "Crypto.hpp"

namespace engram
{
// One save on disk, with the fields that decide whether it can travel. Mirrors
// engram/saves.py, which reads the same `metadata.9.json`.
struct SaveInfo
{
    std::string folderName;
    std::string name;
    std::string buildPatch;
    std::string lifePath;
    std::string difficulty;
    std::string timestampString;
    int level = 0;
    int streetCred = 0;
    int gameVersion = 0;
    int saveVersion = 0;
    double playTime = 0.0;
    bool isModded = false;
    bool needsPhantomLiberty = false;
    uint64_t sizeBytes = 0;

    // One line for a menu: "level 60 StreetKid, 105h 15m played, 19:09:31, 2.08.2026".
    std::string Describe() const;
};

SaveInfo ReadSave(const std::filesystem::path& aFolder);

// Every readable save, newest first.
std::vector<SaveInfo> ListSaves(const std::filesystem::path& aRoot);

// The save's three files, under their plain names.
Files CollectSave(const std::filesystem::path& aFolder);

// The metadata as JSON text, for the manifest.
std::string SaveMetadataJson(const std::filesystem::path& aFolder);

// A slot name nothing occupies, so an import never overwrites a save.
std::string FreeSlotName(const std::filesystem::path& aRoot, const std::string& aPrefix);

// Write a save into the save folder. Assembled under a temporary name and renamed into
// place at the end, so the game never sees a half written save. Refuses to overwrite.
std::filesystem::path InstallSave(const std::filesystem::path& aRoot,
                                  const std::string& aSlotName, const Files& aFiles);

// Highest game version among the saves here, which is what this machine's game writes.
// Zero when there are no saves to go on.
int LocalGameVersion(const std::filesystem::path& aRoot);
} // namespace engram
