#include "Jobs.hpp"

#include <atomic>
#include <functional>
#include <memory>
#include <map>
#include <mutex>
#include <thread>

namespace
{
struct Job
{
    engram::JobReport report;
    std::thread worker;
    std::atomic<bool> cancelled{false};
};

std::mutex g_mutex;
std::map<int32_t, std::shared_ptr<Job>> g_jobs;
int32_t g_next = 1;

std::shared_ptr<Job> Find(int32_t aId)
{
    std::lock_guard<std::mutex> lock(g_mutex);
    const auto found = g_jobs.find(aId);
    return found == g_jobs.end() ? nullptr : found->second;
}

// Hands a job to a worker thread and returns its id straight away. The report is only ever
// written under the lock, and only by the worker, so the menu can read it on any frame.
int32_t Begin(std::function<void(Job&)> aWork)
{
    auto job = std::make_shared<Job>();
    job->report.state = engram::JobState::Working;

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
                std::lock_guard<std::mutex> lock(g_mutex);
                job->report.state = engram::JobState::Failed;
                job->report.message = exc.what();
            }
            catch (...)
            {
                std::lock_guard<std::mutex> lock(g_mutex);
                job->report.state = engram::JobState::Failed;
                job->report.message = "something went wrong that Engram could not name";
            }
        });
    return id;
}

void Finish(Job& aJob, engram::JobState aState, const std::string& aMessage)
{
    std::lock_guard<std::mutex> lock(g_mutex);
    aJob.report.state = aState;
    aJob.report.message = aMessage;
}

// Phases two to four of the mod port fill these in. Until then they say so plainly rather
// than pretending to work, because a button that silently does nothing is worse than one
// that explains itself.
constexpr const char* kNotBuilt =
    "This part of the mod is not built yet. Until it is, share and receive a save with the "
    "Engram tool outside the game. Everything else here is real.";
} // namespace

namespace engram
{
int32_t StartShare(const std::string& aSaveName)
{
    if (aSaveName.empty())
    {
        return 0;
    }
    return Begin([](Job& job) { Finish(job, JobState::Failed, kNotBuilt); });
}

int32_t StartFetch(const std::string& aCode)
{
    if (aCode.empty())
    {
        return 0;
    }
    return Begin([](Job& job) { Finish(job, JobState::Failed, kNotBuilt); });
}

int32_t StartWrite(int32_t aFetchJob, bool)
{
    if (aFetchJob <= 0)
    {
        return 0;
    }
    return Begin([](Job& job) { Finish(job, JobState::Failed, kNotBuilt); });
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
