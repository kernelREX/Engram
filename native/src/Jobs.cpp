#include "Jobs.hpp"

#include <atomic>
#include <chrono>
#include <functional>
#include <map>
#include <memory>
#include <mutex>
#include <thread>

#include <nlohmann/json.hpp>

#include "Code.hpp"
#include "Container.hpp"
#include "Crypto.hpp"
#include "Http.hpp"
#include "Mods.hpp"
#include "SaveData.hpp"
#include "SaveFolder.hpp"
#include "Version.hpp"

using json = nlohmann::json;

namespace
{
struct Job
{
    engram::JobReport report;
    std::thread worker;
    std::atomic<bool> cancelled{false};

    // A fetch job holds what it downloaded so a later write job can use it without
    // fetching twice.
    engram::Files files;
    std::string manifestJson;
};

std::mutex g_mutex;
std::map<int32_t, std::shared_ptr<Job>> g_jobs;
int32_t g_next = 1;

std::filesystem::path g_gameDir;
std::mutex g_gameMutex;

std::shared_ptr<Job> Find(int32_t aId)
{
    std::lock_guard<std::mutex> lock(g_mutex);
    const auto found = g_jobs.find(aId);
    return found == g_jobs.end() ? nullptr : found->second;
}

void Say(Job& aJob, const std::string& aMessage)
{
    std::lock_guard<std::mutex> lock(g_mutex);
    aJob.report.message = aMessage;
}

void Finish(Job& aJob, engram::JobState aState, const std::string& aMessage)
{
    std::lock_guard<std::mutex> lock(g_mutex);
    aJob.report.state = aState;
    aJob.report.message = aMessage;
}

int32_t Begin(engram::JobKind aKind, std::function<void(Job&)> aWork)
{
    auto job = std::make_shared<Job>();
    job->report.state = engram::JobState::Working;
    job->report.kind = aKind;

    int32_t id = 0;
    {
        std::lock_guard<std::mutex> lock(g_mutex);
        id = g_next++;
        g_jobs[id] = job;
    }

    job->worker = std::thread(
        [job, work = std::move(aWork)]()
        {
            try
            {
                work(*job);
            }
            catch (const std::exception& exc)
            {
                Finish(*job, engram::JobState::Failed, exc.what());
            }
            catch (...)
            {
                Finish(*job, engram::JobState::Failed,
                       "Something went wrong that Engram could not name.");
            }
        });
    return id;
}

// "1 hour", "12 hours", "3 days": what the sender chose, in words.
std::string DescribeHours(int aHours)
{
    if (aHours <= 1)
    {
        return "1 hour";
    }
    if (aHours % 24 == 0)
    {
        const int days = aHours / 24;
        return std::to_string(days) + (days == 1 ? " day" : " days");
    }
    return std::to_string(aHours) + " hours";
}

std::string NowIso()
{
    const auto now = std::chrono::system_clock::now();
    const auto seconds = std::chrono::system_clock::to_time_t(now);
    std::tm parts{};
    gmtime_s(&parts, &seconds);
    char buffer[32];
    std::strftime(buffer, sizeof(buffer), "%Y-%m-%dT%H:%M:%S+00:00", &parts);
    return buffer;
}

std::filesystem::path GameDir()
{
    std::lock_guard<std::mutex> lock(g_gameMutex);
    return g_gameDir;
}

// The manifest, in the shape engram/manifest.py reads.
std::string BuildManifest(const engram::SaveInfo& aSave, const std::string& aSaveMetadata,
                          const engram::ModSet& aMods, const engram::Files& aFiles)
{
    json save = json::object();
    try
    {
        const json document = json::parse(aSaveMetadata);
        const json& block = document["Data"]["metadata"];
        for (const char* field :
             {"name", "buildPatch", "gameVersion", "saveVersion", "playthroughID", "isModded",
              "level", "streetCred", "lifePath", "difficulty", "playTime", "playthroughTime",
              "timestampString", "locationName", "trackedQuest", "additionalContentIds",
              "platform", "isEndGameSave", "isPointOfNoReturn"})
        {
            if (block.contains(field))
            {
                save[field] = block[field];
            }
        }
    }
    catch (const std::exception&)
    {
        save["name"] = aSave.name;
        save["gameVersion"] = aSave.gameVersion;
        save["buildPatch"] = aSave.buildPatch;
    }

    json hashes = json::object();
    for (const auto& [name, data] : aFiles)
    {
        hashes[name] = engram::Sha256Hex(data);
    }

    json requires_ = json::object();
    bool needsPhantomLiberty = false;
    if (save.contains("additionalContentIds"))
    {
        for (const auto& id : save["additionalContentIds"])
        {
            if (id.is_string() && id.get<std::string>() == "EP1")
            {
                needsPhantomLiberty = true;
            }
        }
    }
    requires_["phantomLiberty"] = needsPhantomLiberty;
    requires_["gameVersion"] = save.value("gameVersion", 0);
    requires_["buildPatch"] = save.value("buildPatch", std::string());

    json manifest;
    manifest["engramVersion"] = 1;
    manifest["engramRelease"] = engram::kVersion;
    manifest["exportedAt"] = NowIso();
    manifest["sourceFolder"] = aSave.folderName;
    manifest["save"] = save;
    manifest["requires"] = requires_;
    manifest["phantomLiberty"] = aMods.phantomLiberty;
    manifest["mods"] = json::parse(engram::ModsToJson(aMods));
    manifest["sha256"] = hashes;
    return manifest.dump(2);
}

void VerifyHashes(const json& aManifest, const engram::Files& aFiles)
{
    if (!aManifest.contains("sha256") || !aManifest["sha256"].is_object() ||
        aManifest["sha256"].empty())
    {
        throw std::runtime_error("the manifest carries no hashes, so nothing can be checked");
    }

    for (const auto& [name, expected] : aManifest["sha256"].items())
    {
        const auto found = aFiles.find(name);
        if (found == aFiles.end())
        {
            throw std::runtime_error("the manifest lists a file the container does not hold: " +
                                     name);
        }
        if (engram::Sha256Hex(found->second) != expected.get<std::string>())
        {
            throw std::runtime_error(
                name + " does not match its hash. The file was altered after it was packed, "
                       "so Engram will not write it.");
        }
    }

    // sav.dat is a binary going into the game's own loader, so check it looks like one.
    const auto sav = aFiles.find("sav.dat");
    if (sav != aFiles.end())
    {
        static const uint8_t magic[4] = {'V', 'A', 'S', 'C'};
        if (sav->second.size() < 4 || std::memcmp(sav->second.data(), magic, 4) != 0)
        {
            throw std::runtime_error(
                "sav.dat does not start like a Cyberpunk save. Engram will not hand that to "
                "the game.");
        }
    }
}

bool ProcessRunning(const wchar_t* aName);
} // namespace

namespace engram
{
void SetGameDir(const std::filesystem::path& aPath)
{
    std::lock_guard<std::mutex> lock(g_gameMutex);
    g_gameDir = aPath;
}

int32_t StartShare(const std::string& aSaveName, int aHours)
{
    if (aSaveName.empty())
    {
        return 0;
    }

    return Begin(
        JobKind::Share,
        [aSaveName, aHours](Job& job)
        {
            const auto root = SaveFolder();
            const auto folder = root / aSaveName;
            if (!std::filesystem::is_directory(folder))
            {
                Finish(job, JobState::Failed, "There is no save called " + aSaveName + ".");
                return;
            }

            Say(job, "Reading the save");
            const SaveInfo info = ReadSave(folder);
            const Files files = CollectSave(folder);
            const std::string metadata = SaveMetadataJson(folder);

            Say(job, "Checking which mods are installed");
            const ModSet mods = ScanMods(GameDir());

            // The sender is told what is travelling before they read the code out.
            const Finding alert = ModsOnThisSave(mods);
            {
                std::lock_guard<std::mutex> lock(g_mutex);
                job.report.findings.push_back(alert.summary);
                for (const auto& item : alert.items)
                {
                    job.report.findings.push_back("  " + item);
                }
                job.report.modded = !mods.entries.empty();
            }

            const std::string manifest = BuildManifest(info, metadata, mods, files);
            const std::string secret = NewSecret();

            std::string lastError;
            for (const auto& host : Hosts())
            {
                if (job.cancelled)
                {
                    Finish(job, JobState::Failed, "Cancelled.");
                    return;
                }

                Say(job, "Packing and sealing the save");
                const Bytes blob = Pack(manifest, files, secret, host.key);

                Say(job, "Uploading to " + host.label);
                try
                {
                    const UploadResult result = Upload(host, blob, aHours);
                    const std::string code = FormatCode(host, result.fileId, secret);

                    std::lock_guard<std::mutex> lock(g_mutex);
                    job.report.code = code;
                    job.report.state = JobState::Done;
                    job.report.message = "Uploaded to " + host.label + ". The code stops "
                                         "working after " + DescribeHours(aHours) + ".";
                    return;
                }
                catch (const std::exception& exc)
                {
                    lastError = exc.what();
                }
            }

            Finish(job, JobState::Failed,
                   lastError.empty() ? "No host would take the file." : lastError);
        });
}

int32_t StartFetch(const std::string& aCode)
{
    if (aCode.empty())
    {
        return 0;
    }

    return Begin(
        JobKind::Fetch,
        [aCode](Job& job)
        {
            Code parsed;
            std::string error;
            if (!ParseCode(aCode, parsed, error))
            {
                Finish(job, JobState::Failed, error);
                return;
            }

            Say(job, "Downloading from " + parsed.host->label);
            const Bytes blob = Download(*parsed.host, parsed.fileId);

            Say(job, "Opening it");
            const Bundle bundle = Unpack(blob, parsed.secret);

            json manifest;
            try
            {
                manifest = json::parse(bundle.manifestJson);
            }
            catch (const std::exception&)
            {
                Finish(job, JobState::Failed, "The manifest inside is not readable.");
                return;
            }

            const int version = manifest.value("engramVersion", 0);
            if (version > 1)
            {
                Finish(job, JobState::Failed,
                       "This save was packed by a newer Engram. Update the mod.");
                return;
            }

            Say(job, "Checking it against this machine");
            VerifyHashes(manifest, bundle.files);

            const ModSet senderMods = ModsFromJson(manifest.dump());
            const ModSet receiverMods = ScanMods(GameDir());
            const auto root = SaveFolder();

            const CheckReport report = BuildReport(
                manifest.value("save", json::object()).dump(), senderMods, receiverMods,
                LocalGameVersion(root), ProcessRunning(L"Cyberpunk2077.exe"),
                ProcessRunning(L"steam.exe"));

            std::lock_guard<std::mutex> lock(g_mutex);
            job.files = bundle.files;
            job.manifestJson = bundle.manifestJson;
            job.report.findings = report.Lines();
            job.report.blocked = report.Blocked();
            job.report.modded = !senderMods.entries.empty();
            job.report.code = report.Summarise();

            const json save = manifest.value("save", json::object());
            const int level = static_cast<int>(save.value("level", 0.0));
            const std::string life = save.value("lifePath", std::string("unknown"));
            const int minutes = static_cast<int>(save.value("playTime", 0.0)) / 60;
            job.report.message = "Level " + std::to_string(level) + " " + life + ", " +
                                 std::to_string(minutes / 60) + "h played, from game " +
                                 save.value("buildPatch", std::string("unknown"));
            job.report.state = JobState::Done;
        });
}

int32_t StartWrite(int32_t aFetchJob, bool aForce)
{
    const auto source = Find(aFetchJob);
    if (!source)
    {
        return 0;
    }

    return Begin(
        JobKind::Write,
        [source, aForce](Job& job)
        {
            Files files;
            bool blocked = false;
            {
                std::lock_guard<std::mutex> lock(g_mutex);
                files = source->files;
                blocked = source->report.blocked;
            }

            if (files.empty())
            {
                Finish(job, JobState::Failed, "There is nothing downloaded to write.");
                return;
            }
            if (blocked && !aForce)
            {
                Finish(job, JobState::Failed,
                       "Engram has not written anything, because of the items marked STOP.");
                return;
            }

            const auto root = SaveFolder();
            const std::string slot = FreeSlotName(root, "EngramSave");

            Say(job, "Writing " + slot);
            const auto written = InstallSave(root, slot, files);

            Finish(job, JobState::Done,
                   "Written as " + slot + ". Start a new session or go back to the main menu "
                   "and it is in the load list.");
            std::lock_guard<std::mutex> lock(g_mutex);
            job.report.code = slot;
        });
}

JobReport Report(int32_t aJob)
{
    const auto job = Find(aJob);
    if (!job)
    {
        return {};
    }
    std::lock_guard<std::mutex> lock(g_mutex);
    return job->report;
}

void Cancel(int32_t aJob)
{
    std::shared_ptr<Job> job;
    {
        std::lock_guard<std::mutex> lock(g_mutex);
        const auto found = g_jobs.find(aJob);
        if (found == g_jobs.end())
        {
            return;
        }
        job = found->second;
        g_jobs.erase(found);
    }

    job->cancelled = true;
    if (job->worker.joinable())
    {
        job->worker.join();
    }
}

void Forget()
{
    std::map<int32_t, std::shared_ptr<Job>> taken;
    {
        std::lock_guard<std::mutex> lock(g_mutex);
        taken.swap(g_jobs);
    }
    for (auto& [id, job] : taken)
    {
        job->cancelled = true;
        if (job->worker.joinable())
        {
            job->worker.join();
        }
    }
}
} // namespace engram

#include <windows.h>

#include <tlhelp32.h>

namespace
{
// Steam Cloud syncs the save folder and will happily overwrite an imported save, and the
// game holds the folder open. Both are worth saying before anything is written.
bool ProcessRunning(const wchar_t* aName)
{
    HANDLE snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (snapshot == INVALID_HANDLE_VALUE)
    {
        return false;
    }

    PROCESSENTRY32W entry{};
    entry.dwSize = sizeof(entry);
    bool found = false;
    if (Process32FirstW(snapshot, &entry))
    {
        do
        {
            if (_wcsicmp(entry.szExeFile, aName) == 0)
            {
                found = true;
                break;
            }
        } while (Process32NextW(snapshot, &entry));
    }
    CloseHandle(snapshot);
    return found;
}
} // namespace
