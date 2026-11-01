#pragma once

#include <filesystem>
#include <string>
#include <vector>

namespace engram
{
// Where Cyberpunk keeps its saves. Asks Windows for the Saved Games known folder rather
// than assuming it sits under the user profile, because people move it.
std::filesystem::path SaveFolder();

// The folders under `aRoot` that are actually saves, newest first by write time. A folder
// counts when it holds sav.dat and a metadata file, which is the same test the standalone
// tool uses.
std::vector<std::string> ListSaveFolders(const std::filesystem::path& aRoot);
} // namespace engram
