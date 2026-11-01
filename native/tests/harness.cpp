// Checks the native half against the Python half, without a game.
//
// The two implementations have to agree byte for byte: a code made in the game must open
// in the standalone tool and the other way round. The only honest way to know that is to
// have each one read what the other wrote, which is what the `pack` and `open` commands
// here are for. `tests/test_crosscompat.py` drives them.
//
//   engram_harness saves                     list the save folder
//   engram_harness key <secret> <context>    print the derived key as hex
//   engram_harness code <host> <id> <secret> print the code for those
//   engram_harness parse <code>              print host, id and secret
//   engram_harness pack <out> <secret> <ctx> <manifest.json> <name=file>...
//   engram_harness open <in> <secret> <outdir>

#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

#include "Code.hpp"
#include "Container.hpp"
#include "Mods.hpp"
#include "SaveData.hpp"
#include "Crypto.hpp"
#include "SaveFolder.hpp"
#include "Version.hpp"

namespace
{
std::string ReadText(const std::string& aPath)
{
    std::ifstream file(aPath, std::ios::binary);
    if (!file)
    {
        throw std::runtime_error("could not read " + aPath);
    }
    return std::string((std::istreambuf_iterator<char>(file)),
                       std::istreambuf_iterator<char>());
}

engram::Bytes ReadFile(const std::string& aPath)
{
    std::ifstream file(aPath, std::ios::binary);
    if (!file)
    {
        throw std::runtime_error("could not read " + aPath);
    }
    return engram::Bytes((std::istreambuf_iterator<char>(file)),
                         std::istreambuf_iterator<char>());
}

void WriteFile(const std::string& aPath, const engram::Bytes& aData)
{
    std::ofstream file(aPath, std::ios::binary);
    if (!file)
    {
        throw std::runtime_error("could not write " + aPath);
    }
    file.write(reinterpret_cast<const char*>(aData.data()),
               static_cast<std::streamsize>(aData.size()));
}

std::string ToHex(const engram::Bytes& aBytes)
{
    static const char* digits = "0123456789abcdef";
    std::string out;
    for (const auto byte : aBytes)
    {
        out.push_back(digits[byte >> 4]);
        out.push_back(digits[byte & 0x0F]);
    }
    return out;
}

int Saves()
{
    std::cout << "Engram native " << engram::kVersion << "\n";
    const auto folder = engram::SaveFolder();
    std::cout << "save folder: " << folder.string() << "\n";
    if (!std::filesystem::is_directory(folder))
    {
        std::cout << "note: that folder does not exist on this machine\n";
        return 0;
    }
    const auto names = engram::ListSaveFolders(folder);
    std::cout << names.size() << " save(s), newest first:\n";
    for (size_t i = 0; i < names.size() && i < 6; ++i)
    {
        std::cout << "  " << names[i] << "\n";
    }
    return names.empty() ? 1 : 0;
}
} // namespace

int main(int argc, char** argv)
{
    std::vector<std::string> args(argv + 1, argv + argc);
    if (args.empty())
    {
        return Saves();
    }

    try
    {
        const std::string& command = args[0];

        if (command == "saves")
        {
            return Saves();
        }

        if (command == "key" && args.size() >= 3)
        {
            const engram::KeyParams params;
            std::cout << ToHex(engram::DeriveKey(args[1], args[2], params)) << "\n";
            return 0;
        }

        if (command == "sha256" && args.size() >= 2)
        {
            std::cout << engram::Sha256Hex(ReadFile(args[1])) << "\n";
            return 0;
        }

        if (command == "code" && args.size() >= 4)
        {
            const auto* host = engram::HostByKey(args[1]);
            if (!host)
            {
                std::cout << "unknown host\n";
                return 1;
            }
            std::cout << engram::FormatCode(*host, args[2], args[3]) << "\n";
            return 0;
        }

        if (command == "mods" && args.size() >= 2)
        {
            const auto mods = engram::ScanMods(args[1]);
            std::cout << engram::ModsToJson(mods) << "\n";
            return 0;
        }

        if (command == "alert" && args.size() >= 2)
        {
            const auto mods = engram::ModsFromJson(ReadText(args[1]));
            const auto alert = engram::ModsOnThisSave(mods);
            std::cout << static_cast<int>(alert.severity) << "\t" << alert.summary << "\n";
            for (const auto& item : alert.items)
            {
                std::cout << item << "\n";
            }
            return 0;
        }

        if (command == "report" && args.size() >= 4)
        {
            const auto report = engram::BuildReport(ReadText(args[1]),
                                                    engram::ModsFromJson(ReadText(args[2])),
                                                    engram::ModsFromJson(ReadText(args[3])),
                                                    args.size() > 4 ? std::stoi(args[4]) : 0,
                                                    false, false);
            std::cout << report.Summarise() << "\n";
            for (const auto& line : report.Lines())
            {
                std::cout << line << "\n";
            }
            return report.Blocked() ? 3 : 0;
        }

        if (command == "parse" && args.size() >= 2)
        {
            engram::Code code;
            std::string error;
            if (!engram::ParseCode(args[1], code, error))
            {
                std::cout << "error: " << error << "\n";
                return 1;
            }
            std::cout << code.host->key << " " << code.fileId << " " << code.secret << "\n";
            std::cout << code.host->UrlFor(code.fileId) << "\n";
            return 0;
        }

        if (command == "pack" && args.size() >= 5)
        {
            const std::string out = args[1];
            const std::string secret = (args[2] == "-") ? "" : args[2];
            const std::string context = (args[3] == "-") ? "" : args[3];
            const auto manifestBytes = ReadFile(args[4]);
            const std::string manifest(manifestBytes.begin(), manifestBytes.end());

            engram::Files files;
            for (size_t i = 5; i < args.size(); ++i)
            {
                const auto split = args[i].find('=');
                if (split == std::string::npos)
                {
                    std::cout << "expected name=path, got " << args[i] << "\n";
                    return 1;
                }
                files[args[i].substr(0, split)] = ReadFile(args[i].substr(split + 1));
            }

            WriteFile(out, engram::Pack(manifest, files, secret, context));
            std::cout << "packed " << out << "\n";
            return 0;
        }

        if (command == "open" && args.size() >= 4)
        {
            const std::string secret = (args[2] == "-") ? "" : args[2];
            const auto bundle = engram::Unpack(ReadFile(args[1]), secret);

            const std::filesystem::path outDir(args[3]);
            std::filesystem::create_directories(outDir);

            std::ofstream manifest((outDir / "manifest.json").string(), std::ios::binary);
            manifest << bundle.manifestJson;
            manifest.close();

            for (const auto& [name, data] : bundle.files)
            {
                WriteFile((outDir / name).string(), data);
                std::cout << name << " " << data.size() << "\n";
            }
            return 0;
        }

        std::cout << "unknown command\n";
        return 2;
    }
    catch (const std::exception& exc)
    {
        std::cout << "error: " << exc.what() << "\n";
        return 1;
    }
}
