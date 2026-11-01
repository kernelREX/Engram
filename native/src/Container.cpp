#include "Container.hpp"

#include <cstring>
#include <stdexcept>

#include <nlohmann/json.hpp>

#include "miniz.h"

using json = nlohmann::json;

namespace
{
constexpr size_t kHeaderLimit = 64 * 1024;

// Python writes the header with sorted keys and no spaces. nlohmann's default object is a
// sorted map and dump() with no indent is compact, so the two agree without extra work.
std::string HeaderBytes(const json& aHeader)
{
    return aHeader.dump();
}

void PutU32LE(engram::Bytes& aOut, uint32_t aValue)
{
    aOut.push_back(static_cast<uint8_t>(aValue));
    aOut.push_back(static_cast<uint8_t>(aValue >> 8));
    aOut.push_back(static_cast<uint8_t>(aValue >> 16));
    aOut.push_back(static_cast<uint8_t>(aValue >> 24));
}

uint32_t GetU32LE(const engram::Bytes& aFrom, size_t aAt)
{
    return static_cast<uint32_t>(aFrom[aAt]) | (static_cast<uint32_t>(aFrom[aAt + 1]) << 8) |
           (static_cast<uint32_t>(aFrom[aAt + 2]) << 16) |
           (static_cast<uint32_t>(aFrom[aAt + 3]) << 24);
}

std::string ToHex(const engram::Bytes& aBytes)
{
    static const char* digits = "0123456789abcdef";
    std::string out;
    out.reserve(aBytes.size() * 2);
    for (const auto byte : aBytes)
    {
        out.push_back(digits[byte >> 4]);
        out.push_back(digits[byte & 0x0F]);
    }
    return out;
}

engram::Bytes FromHex(const std::string& aText)
{
    if (aText.size() % 2)
    {
        throw std::runtime_error("the container's nonce is unreadable");
    }
    engram::Bytes out;
    out.reserve(aText.size() / 2);
    for (size_t i = 0; i < aText.size(); i += 2)
    {
        const auto byte = std::stoul(aText.substr(i, 2), nullptr, 16);
        out.push_back(static_cast<uint8_t>(byte));
    }
    return out;
}

engram::Bytes ZipPayload(const std::string& aManifestJson, const engram::Files& aFiles)
{
    mz_zip_archive archive{};
    if (!mz_zip_writer_init_heap(&archive, 0, 1 << 20))
    {
        throw std::runtime_error("could not start building the container");
    }

    const auto add = [&archive](const std::string& aName, const void* aData, size_t aSize)
    {
        if (!mz_zip_writer_add_mem(&archive, aName.c_str(), aData, aSize, MZ_DEFAULT_LEVEL))
        {
            mz_zip_writer_end(&archive);
            throw std::runtime_error("could not add " + aName + " to the container");
        }
    };

    add(engram::kManifestName, aManifestJson.data(), aManifestJson.size());
    for (const auto& [name, data] : aFiles)
    {
        add(std::string(engram::kSavePrefix) + name, data.data(), data.size());
    }

    void* buffer = nullptr;
    size_t size = 0;
    if (!mz_zip_writer_finalize_heap_archive(&archive, &buffer, &size))
    {
        mz_zip_writer_end(&archive);
        throw std::runtime_error("could not finish building the container");
    }

    engram::Bytes out(static_cast<uint8_t*>(buffer), static_cast<uint8_t*>(buffer) + size);
    mz_zip_writer_end(&archive);
    return out;
}

engram::Bundle ReadPayload(const engram::Bytes& aPayload)
{
    mz_zip_archive archive{};
    if (!mz_zip_reader_init_mem(&archive, aPayload.data(), aPayload.size(), 0))
    {
        throw std::runtime_error("the container's body is not a readable archive");
    }

    engram::Bundle bundle;
    const auto count = mz_zip_reader_get_num_files(&archive);
    uint64_t total = 0;

    for (mz_uint i = 0; i < count; ++i)
    {
        mz_zip_archive_file_stat stat{};
        if (!mz_zip_reader_file_stat(&archive, i, &stat))
        {
            mz_zip_reader_end(&archive);
            throw std::runtime_error("the container has an entry that cannot be read");
        }
        total += stat.m_uncomp_size;
        if (total > engram::kMaxPayload)
        {
            mz_zip_reader_end(&archive);
            throw std::runtime_error(
                "the container unpacks to far more than a save, so it is not opened");
        }

        const std::string name = stat.m_filename;
        size_t size = 0;
        void* data = mz_zip_reader_extract_to_heap(&archive, i, &size, 0);
        if (!data)
        {
            mz_zip_reader_end(&archive);
            throw std::runtime_error("could not read " + name + " out of the container");
        }
        engram::Bytes bytes(static_cast<uint8_t*>(data), static_cast<uint8_t*>(data) + size);
        mz_free(data);

        if (name == engram::kManifestName)
        {
            bundle.manifestJson.assign(bytes.begin(), bytes.end());
            continue;
        }

        const std::string prefix = engram::kSavePrefix;
        if (name.rfind(prefix, 0) != 0 || name.back() == '/')
        {
            mz_zip_reader_end(&archive);
            throw std::runtime_error("the container holds an unexpected entry: " + name);
        }
        const std::string plain = name.substr(prefix.size());
        if (plain.empty() || plain == "." || plain == ".." ||
            plain.find('/') != std::string::npos || plain.find('\\') != std::string::npos)
        {
            mz_zip_reader_end(&archive);
            throw std::runtime_error("the container holds an unsafe file name: " + name);
        }
        bundle.files[plain] = std::move(bytes);
    }

    mz_zip_reader_end(&archive);

    if (bundle.manifestJson.empty())
    {
        throw std::runtime_error("the container has no manifest");
    }
    if (bundle.files.empty())
    {
        throw std::runtime_error("the container holds a manifest but no save");
    }
    return bundle;
}
} // namespace

namespace engram
{
Bytes Pack(const std::string& aManifestJson, const Files& aFiles, const std::string& aSecret,
           const std::string& aContext)
{
    const Bytes payload = ZipPayload(aManifestJson, aFiles);
    if (payload.size() > kMaxPayload)
    {
        throw std::runtime_error("this save is far larger than Engram will carry");
    }

    json header;
    Bytes body;

    if (aSecret.empty())
    {
        header["enc"] = "none";
        header["format"] = kFormatVersion;
        body = payload;
    }
    else
    {
        const KeyParams params;
        const Bytes key = DeriveKey(aSecret, aContext, params);

        header["context"] = aContext;
        header["enc"] = "aes-256-gcm";
        header["format"] = kFormatVersion;
        header["kdf"] = {{"kdf", "scrypt"}, {"n", params.n}, {"p", params.p}, {"r", params.r}};

        // The associated data is the header as it will be written but with the nonce
        // blanked, which is what the Python computes on both sides.
        json probeHeader = header;
        probeHeader["nonce"] = "";
        const std::string probe = HeaderBytes(probeHeader);

        Bytes aad(kMagic, kMagic + kMagicSize);
        aad.insert(aad.end(), probe.begin(), probe.end());

        Bytes nonce;
        Encrypt(payload, key, aad, nonce, body);
        header["nonce"] = ToHex(nonce);
    }

    const std::string head = HeaderBytes(header);
    Bytes out(kMagic, kMagic + kMagicSize);
    PutU32LE(out, static_cast<uint32_t>(head.size()));
    out.insert(out.end(), head.begin(), head.end());
    out.insert(out.end(), body.begin(), body.end());
    return out;
}

namespace
{
json ReadHeader(const Bytes& aBlob, size_t& aBodyAt)
{
    if (aBlob.size() < kMagicSize + 4)
    {
        throw std::runtime_error("this file is too short to be an Engram container");
    }
    if (std::memcmp(aBlob.data(), kMagic, kMagicSize) != 0)
    {
        if (std::memcmp(aBlob.data(), kMagic, 6) == 0)
        {
            throw std::runtime_error(
                "this container is a newer format than this Engram reads. Update Engram.");
        }
        throw std::runtime_error("this file is not an Engram container");
    }

    const uint32_t length = GetU32LE(aBlob, kMagicSize);
    if (length == 0 || length > kHeaderLimit)
    {
        throw std::runtime_error("the container's header length is not sensible");
    }
    const size_t start = kMagicSize + 4;
    if (aBlob.size() < start + length)
    {
        throw std::runtime_error("the container's header is truncated");
    }

    const std::string raw(aBlob.begin() + start, aBlob.begin() + start + length);
    aBodyAt = start + length;
    try
    {
        return json::parse(raw);
    }
    catch (const std::exception&)
    {
        throw std::runtime_error("the container's header is not readable");
    }
}
} // namespace

bool IsEncrypted(const Bytes& aBlob)
{
    size_t bodyAt = 0;
    const json header = ReadHeader(aBlob, bodyAt);
    return header.value("enc", std::string("none")) != "none";
}

Bundle Unpack(const Bytes& aBlob, const std::string& aSecret)
{
    size_t bodyAt = 0;
    const json header = ReadHeader(aBlob, bodyAt);
    const Bytes body(aBlob.begin() + bodyAt, aBlob.end());
    const std::string encryption = header.value("enc", std::string("none"));

    Bytes payload;
    if (encryption == "none")
    {
        payload = body;
    }
    else if (encryption == "aes-256-gcm")
    {
        if (aSecret.empty())
        {
            throw std::runtime_error(
                "this container is sealed and no code was given, so there is no key to "
                "open it with");
        }

        KeyParams params;
        if (header.contains("kdf"))
        {
            const auto& kdf = header["kdf"];
            if (kdf.value("kdf", std::string("scrypt")) != "scrypt")
            {
                throw std::runtime_error(
                    "this file uses a key derivation this Engram does not know. Update Engram.");
            }
            params.n = kdf.value("n", params.n);
            params.r = kdf.value("r", params.r);
            params.p = kdf.value("p", params.p);
        }

        const std::string context = header.value("context", std::string());
        const Bytes nonce = FromHex(header.value("nonce", std::string()));
        const Bytes key = DeriveKey(aSecret, context, params);

        json probeHeader = header;
        probeHeader["nonce"] = "";
        const std::string probe = HeaderBytes(probeHeader);

        Bytes aad(kMagic, kMagic + kMagicSize);
        aad.insert(aad.end(), probe.begin(), probe.end());

        if (!Decrypt(body, key, nonce, aad, payload))
        {
            throw std::runtime_error(
                "The save downloaded, but the code did not open it. The last part of the "
                "code is wrong, or the file was altered on the host.");
        }
    }
    else
    {
        throw std::runtime_error(
            "this container is sealed with something this Engram does not know. Update Engram.");
    }

    return ReadPayload(payload);
}
} // namespace engram
