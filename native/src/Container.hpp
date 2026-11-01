#pragma once

#include <map>
#include <string>

#include "Crypto.hpp"

namespace engram
{
// The `.engram` file. Mirrors engram/container.py byte for byte, because a code shared
// from the game has to open in the standalone tool and the other way round.
//
//     magic    8 bytes   ENGRAM\0\1, the last byte being the format version
//     length   4 bytes   little endian length of the header
//     header   JSON      how the body is sealed, and nothing about the save
//     body               a zip, or that zip sealed with AES-256-GCM
//
// The header is plaintext because it has to be read before the key exists, and it is fed
// to the cipher as associated data, so editing it breaks the tag.

constexpr const char* kMagic = "ENGRAM\x00\x01";
constexpr size_t kMagicSize = 8;
constexpr int kFormatVersion = 1;

constexpr const char* kManifestName = "manifest.json";
constexpr const char* kSavePrefix = "save/";

// Ordinary saves are about six megabytes. This is the ceiling on what will be opened, so a
// broken or hostile container cannot be made to fill memory.
constexpr size_t kMaxPayload = 256ull * 1024 * 1024;

using Files = std::map<std::string, Bytes>;

struct Bundle
{
    std::string manifestJson;
    Files files;
};

// Builds a container. With a secret, the body is sealed and `aContext` is mixed into the
// key, which is the host key for a shared save.
Bytes Pack(const std::string& aManifestJson, const Files& aFiles, const std::string& aSecret,
           const std::string& aContext);

// Opens one. Throws std::runtime_error with something worth showing a person.
Bundle Unpack(const Bytes& aBlob, const std::string& aSecret);

bool IsEncrypted(const Bytes& aBlob);
} // namespace engram
