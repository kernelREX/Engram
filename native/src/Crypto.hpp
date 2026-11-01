#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace engram
{
using Bytes = std::vector<uint8_t>;

constexpr size_t kKeyBytes = 32;
constexpr size_t kNonceBytes = 12;
constexpr size_t kTagBytes = 16;

// scrypt cost, recorded alongside the data it was used on so raising it later does not
// strand files written today. These have to match engram/crypto.py.
struct KeyParams
{
    uint64_t n = 1u << 16;
    uint32_t r = 8;
    uint32_t p = 1;
};

Bytes Sha256(const Bytes& aData);
std::string Sha256Hex(const Bytes& aData);

// PBKDF2-HMAC-SHA256, which scrypt is built on top of.
Bytes Pbkdf2Sha256(const Bytes& aPassword, const Bytes& aSalt, uint32_t aIterations,
                   size_t aLength);

// scrypt, matching Python's hashlib.scrypt. The standard library has no scrypt and neither
// does Windows, so the ROMix half is implemented here on top of PBKDF2.
Bytes Scrypt(const Bytes& aPassword, const Bytes& aSalt, const KeyParams& aParams,
             size_t aLength);

// The salt the key is derived with: sha256(b"engram-v1-salt\0" + context).
Bytes SaltFor(const std::string& aContext);

// The content key for a code's secret half.
Bytes DeriveKey(const std::string& aSecret, const std::string& aContext,
                const KeyParams& aParams);

// AES-256-GCM. Encrypt returns nonce and ciphertext with the tag appended, the same shape
// the Python writes.
void Encrypt(const Bytes& aPlain, const Bytes& aKey, const Bytes& aAad, Bytes& aNonceOut,
             Bytes& aCipherOut);

// Returns false when the tag does not verify, which means the wrong secret or a changed
// file. It never throws on a bad key, because that is an ordinary outcome.
bool Decrypt(const Bytes& aCipher, const Bytes& aKey, const Bytes& aNonce, const Bytes& aAad,
             Bytes& aPlainOut);

// Cryptographically strong random bytes.
Bytes RandomBytes(size_t aCount);
} // namespace engram
