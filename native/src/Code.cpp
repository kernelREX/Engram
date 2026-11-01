#include "Code.hpp"

#include <algorithm>
#include <cmath>
#include <regex>
#include <stdexcept>

#include "Crypto.hpp"

namespace engram
{
namespace crockford
{
const char* kAlphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";

namespace
{
int ValueOf(char aChar)
{
    const char upper = static_cast<char>(std::toupper(static_cast<unsigned char>(aChar)));
    // The characters the alphabet leaves out, folded the way Crockford specifies.
    if (upper == 'I' || upper == 'L')
    {
        return 1;
    }
    if (upper == 'O')
    {
        return 0;
    }
    const char* found = std::strchr(kAlphabet, upper);
    return found ? static_cast<int>(found - kAlphabet) : -1;
}
} // namespace

std::string Normalise(const std::string& aText)
{
    std::string out;
    for (const char character : aText)
    {
        if (character == '-' || character == ' ' || character == '\t' || character == '_')
        {
            continue;
        }
        const int value = ValueOf(character);
        if (value < 0)
        {
            throw std::runtime_error(std::string("'") + character +
                                     "' is not a character a code can contain");
        }
        out.push_back(kAlphabet[value]);
    }
    return out;
}

std::string EncodeInt(uint64_t aValue, size_t aWidth)
{
    std::string out(aWidth, '0');
    for (size_t i = 0; i < aWidth; ++i)
    {
        out[aWidth - 1 - i] = kAlphabet[aValue % 32];
        aValue /= 32;
    }
    if (aValue != 0)
    {
        throw std::runtime_error("value does not fit in the characters given");
    }
    return out;
}

uint64_t DecodeInt(const std::string& aText)
{
    uint64_t value = 0;
    for (const char character : Normalise(aText))
    {
        value = value * 32 + static_cast<uint64_t>(ValueOf(character));
    }
    return value;
}

size_t WidthFor(size_t aBits)
{
    return std::max<size_t>(1, (aBits + 4) / 5);
}
} // namespace crockford

namespace
{
const std::string kBase36 = "0123456789abcdefghijklmnopqrstuvwxyz";
const std::string kBase62 =
    "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz";

constexpr size_t kMaxIdLength = 31;

const std::vector<Host> g_hosts = {
    Host{'C', "litterbox", "Litterbox", "https://litter.catbox.moe/{id}.bin", kBase36,
         "https://litterbox.catbox.moe/resources/internals/api.php", "engram.bin", "72h", 6,
         1024ull * 1024 * 1024},
    Host{'N', "nullpointer", "0x0.st", "https://0x0.st/{id}.bin", kBase62, "https://0x0.st",
         "engram.bin", "72", -1, 512ull * 1024 * 1024},
};

uint64_t IdToInt(const Host& aHost, const std::string& aId)
{
    const uint64_t base = aHost.idCharset.size();
    uint64_t value = 0;
    for (const char character : aId)
    {
        const auto at = aHost.idCharset.find(character);
        if (at == std::string::npos)
        {
            throw std::runtime_error("the file id contains a character this host does not use");
        }
        value = value * base + static_cast<uint64_t>(at);
    }
    return value;
}

std::string IntToId(const Host& aHost, uint64_t aValue, size_t aLength)
{
    const uint64_t base = aHost.idCharset.size();
    std::string out(aLength, aHost.idCharset[0]);
    for (size_t i = 0; i < aLength; ++i)
    {
        out[aLength - 1 - i] = aHost.idCharset[static_cast<size_t>(aValue % base)];
        aValue /= base;
    }
    if (aValue != 0)
    {
        throw std::runtime_error("the code's middle does not decode to a file id");
    }
    return out;
}

void ValidateId(const Host& aHost, const std::string& aId)
{
    if (aId.empty())
    {
        throw std::runtime_error(aHost.label + " returned an empty file id");
    }
    for (const char character : aId)
    {
        if (aHost.idCharset.find(character) == std::string::npos)
        {
            throw std::runtime_error(aHost.label +
                                     " returned a file id outside the alphabet Engram knows");
        }
    }
    if (aHost.IsFixedWidth() && aId.size() != static_cast<size_t>(aHost.idWidth))
    {
        throw std::runtime_error(aHost.label +
                                 " returned a file id of the wrong length. The host has "
                                 "changed; update the host list.");
    }
    if (!aHost.IsFixedWidth() && aId.size() > kMaxIdLength)
    {
        throw std::runtime_error(aHost.label + " returned a file id that is too long");
    }
}
} // namespace

std::string Host::UrlFor(const std::string& aId) const
{
    const auto at = urlTemplate.find("{id}");
    return urlTemplate.substr(0, at) + aId + urlTemplate.substr(at + 4);
}

std::string Host::IdFromUrl(const std::string& aUrl) const
{
    const auto at = urlTemplate.find("{id}");
    const std::string head = urlTemplate.substr(0, at);
    const std::string tail = urlTemplate.substr(at + 4);

    std::string url = aUrl;
    while (!url.empty() && (url.back() == '\n' || url.back() == '\r' || url.back() == ' '))
    {
        url.pop_back();
    }

    if (url.size() <= head.size() + tail.size())
    {
        return {};
    }
    if (url.compare(0, head.size(), head) != 0)
    {
        return {};
    }
    if (url.compare(url.size() - tail.size(), tail.size(), tail) != 0)
    {
        return {};
    }

    const std::string id = url.substr(head.size(), url.size() - head.size() - tail.size());
    for (const char character : id)
    {
        if (idCharset.find(character) == std::string::npos)
        {
            return {};
        }
    }
    return id;
}

size_t Host::CharsForIdOfLength(size_t aLength) const
{
    const double bits = static_cast<double>(aLength) * std::log2(static_cast<double>(idCharset.size()));
    return crockford::WidthFor(static_cast<size_t>(std::ceil(bits)));
}

size_t Host::IdChars() const
{
    return CharsForIdOfLength(static_cast<size_t>(idWidth));
}

const std::vector<Host>& Hosts()
{
    return g_hosts;
}

const Host* HostByTag(char aTag)
{
    const char upper = static_cast<char>(std::toupper(static_cast<unsigned char>(aTag)));
    for (const auto& host : g_hosts)
    {
        if (host.tag == upper)
        {
            return &host;
        }
    }
    return nullptr;
}

const Host* HostByKey(const std::string& aKey)
{
    for (const auto& host : g_hosts)
    {
        if (host.key == aKey)
        {
            return &host;
        }
    }
    return nullptr;
}

std::string NewSecret()
{
    // Uniform over the whole space: forty bits taken from the system generator.
    const auto random = RandomBytes(8);
    uint64_t value = 0;
    for (const auto byte : random)
    {
        value = (value << 8) | byte;
    }
    uint64_t limit = 1;
    for (size_t i = 0; i < kSecretChars; ++i)
    {
        limit *= 32;
    }
    return crockford::EncodeInt(value % limit, kSecretChars);
}

std::string Group(const std::string& aText, size_t aSize)
{
    std::string out;
    for (size_t i = 0; i < aText.size(); i += aSize)
    {
        if (i)
        {
            out.push_back('-');
        }
        out += aText.substr(i, aSize);
    }
    return out;
}

std::string FormatCode(const Host& aHost, const std::string& aFileId,
                       const std::string& aSecret, bool aGrouped)
{
    ValidateId(aHost, aFileId);
    const std::string secret = crockford::Normalise(aSecret);
    if (secret.size() != kSecretChars)
    {
        throw std::runtime_error("a secret is eight characters");
    }

    const uint64_t value = IdToInt(aHost, aFileId);
    std::string body;
    if (aHost.IsFixedWidth())
    {
        body = crockford::EncodeInt(value, aHost.IdChars());
    }
    else
    {
        body = crockford::EncodeInt(aFileId.size(), 1) +
               crockford::EncodeInt(value, aHost.CharsForIdOfLength(aFileId.size()));
    }

    const std::string text = std::string(1, aHost.tag) + body + secret;
    return aGrouped ? Group(text) : text;
}

bool ParseCode(const std::string& aText, Code& aOut, std::string& aError)
{
    std::string raw = aText;
    raw.erase(0, raw.find_first_not_of(" \t\r\n"));
    const auto last = raw.find_last_not_of(" \t\r\n");
    raw = (last == std::string::npos) ? "" : raw.substr(0, last + 1);

    if (raw.empty())
    {
        aError = "no code given";
        return false;
    }
    if (raw.find("://") != std::string::npos)
    {
        aError =
            "That is the download link, not the code. The link alone cannot open the save, "
            "because the last eight characters of the code never left the sender's machine. "
            "Ask them for the whole code.";
        return false;
    }

    std::string body;
    try
    {
        body = crockford::Normalise(raw);
    }
    catch (const std::exception& exc)
    {
        aError = exc.what();
        return false;
    }

    if (body.empty())
    {
        aError = "no code given";
        return false;
    }

    const Host* host = HostByTag(body[0]);
    if (!host)
    {
        aError = std::string("A code starting with '") + body[0] +
                 "' is for a host this version does not know.";
        return false;
    }

    std::string rest = body.substr(1);
    size_t idChars = 0;
    size_t length = 0;

    if (host->IsFixedWidth())
    {
        idChars = host->IdChars();
        length = static_cast<size_t>(host->idWidth);
        if (rest.size() < idChars)
        {
            aError = "This code is too short to be a " + host->label + " code.";
            return false;
        }
    }
    else
    {
        if (rest.empty())
        {
            aError = "This code is too short to be a " + host->label + " code.";
            return false;
        }
        length = static_cast<size_t>(crockford::DecodeInt(rest.substr(0, 1)));
        rest = rest.substr(1);
        if (length < 1 || length > kMaxIdLength)
        {
            aError = "The code's second character is not a sensible id length.";
            return false;
        }
        idChars = host->CharsForIdOfLength(length);
        if (rest.size() < idChars)
        {
            aError = "This code is too short to be a " + host->label + " code.";
            return false;
        }
    }

    const std::string idPart = rest.substr(0, idChars);
    rest = rest.substr(idChars);

    if (rest.size() != kSecretChars)
    {
        aError = "That code is not the right length. Count the groups and try again.";
        return false;
    }

    try
    {
        aOut.host = host;
        aOut.fileId = IntToId(*host, crockford::DecodeInt(idPart), length);
        aOut.secret = rest;
        aOut.text = Group(body);
    }
    catch (const std::exception& exc)
    {
        aError = exc.what();
        return false;
    }
    return true;
}
} // namespace engram
