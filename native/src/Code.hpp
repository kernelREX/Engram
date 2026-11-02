#pragma once

#include <string>
#include <vector>

#include "Version.hpp"

namespace engram
{
// Crockford base32, the alphabet used for everything a person reads aloud. I, L, O and U
// are absent; on input I and L fold to 1 and O folds to 0. Mirrors engram/crockford.py.
namespace crockford
{
extern const char* kAlphabet;

std::string Normalise(const std::string& aText);
std::string EncodeInt(uint64_t aValue, size_t aWidth);
uint64_t DecodeInt(const std::string& aText);
size_t WidthFor(size_t aBits);
} // namespace crockford

constexpr size_t kSecretChars = 8;
constexpr size_t kGroup = 4;

// A file host, described well enough to build and read a code without touching it.
struct Host
{
    char tag;
    std::string key;
    std::string label;
    std::string urlTemplate;
    std::string idCharset;
    std::string uploadUrl;
    std::string uploadFilename;
    std::string expiry;
    int idWidth;       // -1 when the host's ids vary in length
    uint64_t maxBytes;

    // How this host spells a lifetime of `aHours`. Litterbox wants "72h", 0x0.st wants
    // "72". Values outside what a host accepts are pulled to the nearest one it does.
    std::string ExpirySpelling(int aHours) const;

    std::string UrlFor(const std::string& aId) const;
    std::string IdFromUrl(const std::string& aUrl) const;
    size_t CharsForIdOfLength(size_t aLength) const;
    size_t IdChars() const;
    bool IsFixedWidth() const { return idWidth >= 0; }
};

const std::vector<Host>& Hosts();
const Host* HostByTag(char aTag);
const Host* HostByKey(const std::string& aKey);

struct Code
{
    const Host* host = nullptr;
    std::string fileId;
    std::string secret;
    std::string text;   // grouped, the way it is read out
};

std::string NewSecret();
std::string Group(const std::string& aText, size_t aSize = kGroup);

// Builds a code. Throws std::runtime_error when the host gave back an id it should not have.
std::string FormatCode(const Host& aHost, const std::string& aFileId,
                       const std::string& aSecret, bool aGrouped = true);

// Reads a code back, accepting any casing and any dashes. `aError` is filled with something
// worth showing a person when this returns false.
bool ParseCode(const std::string& aText, Code& aOut, std::string& aError);
} // namespace engram
