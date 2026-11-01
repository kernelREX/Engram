#pragma once

#include <string>

#include "Code.hpp"
#include "Crypto.hpp"

namespace engram
{
// What came back from a successful upload.
struct UploadResult
{
    std::string fileId;
    std::string url;
    std::string deleteToken;
};

// Says what we are and where to find us. Several hosts refuse a default library agent.
std::string UserAgent();

// Put a container on one host. One attempt, no retry loop.
UploadResult Upload(const Host& aHost, const Bytes& aContent);

Bytes Download(const Host& aHost, const std::string& aFileId);
} // namespace engram
