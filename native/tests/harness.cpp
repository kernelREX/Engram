// A standalone check of the parts of the plugin that do not need the game.
//
// The RTTI binding can only be proved by starting Cyberpunk, but the file reading can be
// proved here, against the real save folder, before anything is copied into a game
// directory.

#include <iostream>

#include "SaveFolder.hpp"
#include "Version.hpp"

int main()
{
    std::cout << "Engram native " << engram::kVersion << "\n";

    std::filesystem::path folder;
    try
    {
        folder = engram::SaveFolder();
    }
    catch (const std::exception& exc)
    {
        std::cout << "FAIL: save folder: " << exc.what() << "\n";
        return 1;
    }

    std::cout << "save folder: " << folder.string() << "\n";
    if (!std::filesystem::is_directory(folder))
    {
        std::cout << "note: that folder does not exist on this machine\n";
        return 0;
    }

    const auto names = engram::ListSaveFolders(folder);
    std::cout << names.size() << " save(s), newest first:\n";
    for (std::size_t i = 0; i < names.size() && i < 6; ++i)
    {
        std::cout << "  " << names[i] << "\n";
    }
    return names.empty() ? 1 : 0;
}
