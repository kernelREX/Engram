#include "Crypto.hpp"

#include <cstring>
#include <stdexcept>

#include <windows.h>

#include <bcrypt.h>

#pragma comment(lib, "bcrypt.lib")

namespace
{
constexpr NTSTATUS kOk = 0;

void Check(NTSTATUS aStatus, const char* aWhat)
{
    if (aStatus != kOk)
    {
        throw std::runtime_error(std::string(aWhat) + " failed");
    }
}

// A BCrypt algorithm handle that closes itself.
struct Algorithm
{
    BCRYPT_ALG_HANDLE handle = nullptr;

    Algorithm(LPCWSTR aId, ULONG aFlags = 0)
    {
        Check(BCryptOpenAlgorithmProvider(&handle, aId, nullptr, aFlags), "opening a cipher");
    }
    ~Algorithm()
    {
        if (handle)
        {
            BCryptCloseAlgorithmProvider(handle, 0);
        }
    }
    Algorithm(const Algorithm&) = delete;
    Algorithm& operator=(const Algorithm&) = delete;
};

struct Key
{
    BCRYPT_KEY_HANDLE handle = nullptr;

    ~Key()
    {
        if (handle)
        {
            BCryptDestroyKey(handle);
        }
    }
    Key() = default;
    Key(const Key&) = delete;
    Key& operator=(const Key&) = delete;
};

uint32_t Load32LE(const uint8_t* aFrom)
{
    return static_cast<uint32_t>(aFrom[0]) | (static_cast<uint32_t>(aFrom[1]) << 8) |
           (static_cast<uint32_t>(aFrom[2]) << 16) | (static_cast<uint32_t>(aFrom[3]) << 24);
}

void Store32LE(uint8_t* aTo, uint32_t aValue)
{
    aTo[0] = static_cast<uint8_t>(aValue);
    aTo[1] = static_cast<uint8_t>(aValue >> 8);
    aTo[2] = static_cast<uint8_t>(aValue >> 16);
    aTo[3] = static_cast<uint8_t>(aValue >> 24);
}

uint32_t RotateLeft(uint32_t aValue, int aBits)
{
    return (aValue << aBits) | (aValue >> (32 - aBits));
}

// Salsa20/8 core, the mixing function at the bottom of scrypt.
void Salsa20_8(uint8_t aBlock[64])
{
    uint32_t in[16];
    uint32_t x[16];
    for (int i = 0; i < 16; ++i)
    {
        in[i] = Load32LE(aBlock + i * 4);
        x[i] = in[i];
    }

    for (int round = 0; round < 8; round += 2)
    {
        x[4] ^= RotateLeft(x[0] + x[12], 7);
        x[8] ^= RotateLeft(x[4] + x[0], 9);
        x[12] ^= RotateLeft(x[8] + x[4], 13);
        x[0] ^= RotateLeft(x[12] + x[8], 18);
        x[9] ^= RotateLeft(x[5] + x[1], 7);
        x[13] ^= RotateLeft(x[9] + x[5], 9);
        x[1] ^= RotateLeft(x[13] + x[9], 13);
        x[5] ^= RotateLeft(x[1] + x[13], 18);
        x[14] ^= RotateLeft(x[10] + x[6], 7);
        x[2] ^= RotateLeft(x[14] + x[10], 9);
        x[6] ^= RotateLeft(x[2] + x[14], 13);
        x[10] ^= RotateLeft(x[6] + x[2], 18);
        x[3] ^= RotateLeft(x[15] + x[11], 7);
        x[7] ^= RotateLeft(x[3] + x[15], 9);
        x[11] ^= RotateLeft(x[7] + x[3], 13);
        x[15] ^= RotateLeft(x[11] + x[7], 18);

        x[1] ^= RotateLeft(x[0] + x[3], 7);
        x[2] ^= RotateLeft(x[1] + x[0], 9);
        x[3] ^= RotateLeft(x[2] + x[1], 13);
        x[0] ^= RotateLeft(x[3] + x[2], 18);
        x[6] ^= RotateLeft(x[5] + x[4], 7);
        x[7] ^= RotateLeft(x[6] + x[5], 9);
        x[4] ^= RotateLeft(x[7] + x[6], 13);
        x[5] ^= RotateLeft(x[4] + x[7], 18);
        x[11] ^= RotateLeft(x[10] + x[9], 7);
        x[8] ^= RotateLeft(x[11] + x[10], 9);
        x[9] ^= RotateLeft(x[8] + x[11], 13);
        x[10] ^= RotateLeft(x[9] + x[8], 18);
        x[12] ^= RotateLeft(x[15] + x[14], 7);
        x[13] ^= RotateLeft(x[12] + x[15], 9);
        x[14] ^= RotateLeft(x[13] + x[12], 13);
        x[15] ^= RotateLeft(x[14] + x[13], 18);
    }

    for (int i = 0; i < 16; ++i)
    {
        Store32LE(aBlock + i * 4, x[i] + in[i]);
    }
}

void BlockMix(const uint8_t* aIn, uint8_t* aOut, uint32_t aR)
{
    uint8_t carry[64];
    std::memcpy(carry, aIn + (2 * aR - 1) * 64, 64);

    for (uint32_t i = 0; i < 2 * aR; ++i)
    {
        for (int b = 0; b < 64; ++b)
        {
            carry[b] ^= aIn[i * 64 + b];
        }
        Salsa20_8(carry);
        // The even blocks go to the front half of the output, the odd ones to the back.
        const uint32_t target = (i % 2 == 0) ? (i / 2) : (aR + i / 2);
        std::memcpy(aOut + target * 64, carry, 64);
    }
}

void ROMix(uint8_t* aBlock, uint64_t aN, uint32_t aR)
{
    const size_t blockSize = 128ull * aR;
    std::vector<uint8_t> v(blockSize * static_cast<size_t>(aN));
    std::vector<uint8_t> scratch(blockSize);

    for (uint64_t i = 0; i < aN; ++i)
    {
        std::memcpy(v.data() + static_cast<size_t>(i) * blockSize, aBlock, blockSize);
        BlockMix(aBlock, scratch.data(), aR);
        std::memcpy(aBlock, scratch.data(), blockSize);
    }

    for (uint64_t i = 0; i < aN; ++i)
    {
        const uint64_t j = Load32LE(aBlock + (2 * aR - 1) * 64) & (aN - 1);
        const uint8_t* chosen = v.data() + static_cast<size_t>(j) * blockSize;
        for (size_t b = 0; b < blockSize; ++b)
        {
            aBlock[b] ^= chosen[b];
        }
        BlockMix(aBlock, scratch.data(), aR);
        std::memcpy(aBlock, scratch.data(), blockSize);
    }
}
} // namespace

namespace engram
{
Bytes Sha256(const Bytes& aData)
{
    Algorithm algorithm(BCRYPT_SHA256_ALGORITHM);
    Bytes digest(32);
    Check(BCryptHash(algorithm.handle, nullptr, 0, const_cast<PUCHAR>(aData.data()),
                     static_cast<ULONG>(aData.size()), digest.data(),
                     static_cast<ULONG>(digest.size())),
          "hashing");
    return digest;
}

std::string Sha256Hex(const Bytes& aData)
{
    static const char* digits = "0123456789abcdef";
    const auto digest = Sha256(aData);
    std::string out;
    out.reserve(digest.size() * 2);
    for (const auto byte : digest)
    {
        out.push_back(digits[byte >> 4]);
        out.push_back(digits[byte & 0x0F]);
    }
    return out;
}

Bytes Pbkdf2Sha256(const Bytes& aPassword, const Bytes& aSalt, uint32_t aIterations,
                   size_t aLength)
{
    Algorithm algorithm(BCRYPT_SHA256_ALGORITHM, BCRYPT_ALG_HANDLE_HMAC_FLAG);
    Bytes out(aLength);
    Check(BCryptDeriveKeyPBKDF2(algorithm.handle, const_cast<PUCHAR>(aPassword.data()),
                                static_cast<ULONG>(aPassword.size()),
                                const_cast<PUCHAR>(aSalt.data()),
                                static_cast<ULONG>(aSalt.size()), aIterations, out.data(),
                                static_cast<ULONG>(out.size()), 0),
          "deriving a key");
    return out;
}

Bytes Scrypt(const Bytes& aPassword, const Bytes& aSalt, const KeyParams& aParams,
             size_t aLength)
{
    if (aParams.n < 2 || (aParams.n & (aParams.n - 1)) != 0)
    {
        throw std::runtime_error("scrypt cost must be a power of two");
    }

    const size_t blockSize = 128ull * aParams.r;
    Bytes blocks = Pbkdf2Sha256(aPassword, aSalt, 1, blockSize * aParams.p);

    for (uint32_t i = 0; i < aParams.p; ++i)
    {
        ROMix(blocks.data() + static_cast<size_t>(i) * blockSize, aParams.n, aParams.r);
    }

    return Pbkdf2Sha256(aPassword, blocks, 1, aLength);
}

Bytes SaltFor(const std::string& aContext)
{
    static const char* prefix = "engram-v1-salt";
    Bytes material(prefix, prefix + std::strlen(prefix));
    material.push_back(0);
    material.insert(material.end(), aContext.begin(), aContext.end());
    return Sha256(material);
}

Bytes DeriveKey(const std::string& aSecret, const std::string& aContext,
                const KeyParams& aParams)
{
    const Bytes password(aSecret.begin(), aSecret.end());
    return Scrypt(password, SaltFor(aContext), aParams, kKeyBytes);
}

namespace
{
void MakeAesGcmKey(const Bytes& aKey, Algorithm& aAlgorithm, Key& aHandle)
{
    Check(BCryptSetProperty(aAlgorithm.handle, BCRYPT_CHAINING_MODE,
                            reinterpret_cast<PUCHAR>(const_cast<wchar_t*>(BCRYPT_CHAIN_MODE_GCM)),
                            sizeof(BCRYPT_CHAIN_MODE_GCM), 0),
          "selecting GCM");
    Check(BCryptGenerateSymmetricKey(aAlgorithm.handle, &aHandle.handle, nullptr, 0,
                                     const_cast<PUCHAR>(aKey.data()),
                                     static_cast<ULONG>(aKey.size()), 0),
          "preparing a key");
}

BCRYPT_AUTHENTICATED_CIPHER_MODE_INFO MakeInfo(const Bytes& aNonce, const Bytes& aAad,
                                               Bytes& aTag)
{
    BCRYPT_AUTHENTICATED_CIPHER_MODE_INFO info;
    BCRYPT_INIT_AUTH_MODE_INFO(info);
    info.pbNonce = const_cast<PUCHAR>(aNonce.data());
    info.cbNonce = static_cast<ULONG>(aNonce.size());
    info.pbAuthData = aAad.empty() ? nullptr : const_cast<PUCHAR>(aAad.data());
    info.cbAuthData = static_cast<ULONG>(aAad.size());
    info.pbTag = aTag.data();
    info.cbTag = static_cast<ULONG>(aTag.size());
    return info;
}
} // namespace

void Encrypt(const Bytes& aPlain, const Bytes& aKey, const Bytes& aAad, Bytes& aNonceOut,
             Bytes& aCipherOut)
{
    Algorithm algorithm(BCRYPT_AES_ALGORITHM);
    Key key;
    MakeAesGcmKey(aKey, algorithm, key);

    aNonceOut = RandomBytes(kNonceBytes);
    Bytes tag(kTagBytes);
    auto info = MakeInfo(aNonceOut, aAad, tag);

    ULONG written = 0;
    Bytes cipher(aPlain.size());
    Check(BCryptEncrypt(key.handle, const_cast<PUCHAR>(aPlain.data()),
                        static_cast<ULONG>(aPlain.size()), &info, nullptr, 0, cipher.data(),
                        static_cast<ULONG>(cipher.size()), &written, 0),
          "encrypting");
    cipher.resize(written);

    // The tag goes on the end, which is what the Python side writes and expects.
    cipher.insert(cipher.end(), tag.begin(), tag.end());
    aCipherOut = std::move(cipher);
}

bool Decrypt(const Bytes& aCipher, const Bytes& aKey, const Bytes& aNonce, const Bytes& aAad,
             Bytes& aPlainOut)
{
    if (aCipher.size() < kTagBytes || aNonce.size() != kNonceBytes)
    {
        return false;
    }

    Algorithm algorithm(BCRYPT_AES_ALGORITHM);
    Key key;
    MakeAesGcmKey(aKey, algorithm, key);

    Bytes tag(aCipher.end() - kTagBytes, aCipher.end());
    const Bytes body(aCipher.begin(), aCipher.end() - kTagBytes);
    auto info = MakeInfo(aNonce, aAad, tag);

    ULONG written = 0;
    Bytes plain(body.size());
    const auto status =
        BCryptDecrypt(key.handle, const_cast<PUCHAR>(body.data()),
                      static_cast<ULONG>(body.size()), &info, nullptr, 0, plain.data(),
                      static_cast<ULONG>(plain.size()), &written, 0);
    if (status != kOk)
    {
        return false;
    }
    plain.resize(written);
    aPlainOut = std::move(plain);
    return true;
}

Bytes RandomBytes(size_t aCount)
{
    Bytes out(aCount);
    Check(BCryptGenRandom(nullptr, out.data(), static_cast<ULONG>(out.size()),
                          BCRYPT_USE_SYSTEM_PREFERRED_RNG),
          "getting random bytes");
    return out;
}
} // namespace engram
