"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, ListChecks, Loader2, RotateCw } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { describeError } from "@/lib/admin/errors";
import { formatDateTime } from "@/lib/admin/post-display";
import { api, type components } from "@/lib/api";

type Job = components["schemas"]["JobOut"];
type State = "pending" | "dead";

const jobError = (e: unknown) =>
  describeError(e, {
    JOB_NOT_FOUND: "This job no longer exists.",
    JOB_ALREADY_PROCESSED: "This job has already run.",
  });

function useJobs(state: State) {
  return useQuery({
    queryKey: ["jobs", state],
    queryFn: () => api.get<Job[]>("/api/admin/jobs", { query: { state, limit: 100 } }),
    refetchInterval: 15_000,
  });
}

function JobRow({ job, state }: { job: Job; state: State }) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  async function retry() {
    setBusy(true);
    try {
      await api.post(`/api/admin/jobs/${job.id}/retry`);
      toast.success(`Job #${job.id} queued again`);
      await queryClient.invalidateQueries({ queryKey: ["jobs"] });
    } catch (e) {
      toast.error(jobError(e));
    } finally {
      setBusy(false);
    }
  }

  const panel = `job-${job.id}-details`;
  return (
    <li className="px-3 py-3">
      <div className="flex flex-wrap items-start gap-3">
        <button
          type="button"
          aria-expanded={open}
          aria-controls={panel}
          aria-label={`${open ? "Hide" : "Show"} details of job ${job.id}`}
          onClick={() => setOpen((v) => !v)}
          className="mt-0.5 rounded p-0.5 outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring"
        >
          {open ? (
            <ChevronDown aria-hidden className="size-4" />
          ) : (
            <ChevronRight aria-hidden className="size-4" />
          )}
        </button>
        <div className="min-w-0 flex-1 basis-60 space-y-1">
          <p className="flex flex-wrap items-baseline gap-x-2">
            <span className="font-mono text-sm font-medium">{job.topic}</span>
            <span className="text-xs text-muted-foreground">
              #{job.id} · {job.attempts} {job.attempts === 1 ? "attempt" : "attempts"}
            </span>
          </p>
          {job.last_error && (
            <p className="line-clamp-2 text-sm break-words text-destructive">{job.last_error}</p>
          )}
          <p className="text-xs text-muted-foreground">
            Created {formatDateTime(job.created_at)}
            {state === "pending" && job.next_attempt_at && (
              <> · next try {formatDateTime(job.next_attempt_at)}</>
            )}
            {state === "dead" && job.dead_at && <> · gave up {formatDateTime(job.dead_at)}</>}
          </p>
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={busy}
          aria-label={`Retry job ${job.id}`}
          onClick={() => void retry()}
        >
          {busy ? <Loader2 aria-hidden className="animate-spin" /> : <RotateCw aria-hidden />}
          Retry
        </Button>
      </div>
      {open && (
        <div id={panel} className="mt-3 ml-7 space-y-2">
          {job.last_error && (
            <pre className="max-h-48 overflow-auto rounded-lg bg-muted p-3 text-xs whitespace-pre-wrap">
              {job.last_error}
            </pre>
          )}
          <pre
            aria-label={`Payload of job ${job.id}`}
            className="max-h-64 overflow-auto rounded-lg bg-muted p-3 font-mono text-xs"
          >
            {JSON.stringify(job.payload, null, 2)}
          </pre>
        </div>
      )}
    </li>
  );
}

function JobList({ state }: { state: State }) {
  const queryClient = useQueryClient();
  const list = useJobs(state);
  const [retryingAll, setRetryingAll] = useState(false);

  async function retryAll() {
    setRetryingAll(true);
    try {
      const out = await api.post<{ requeued: number }>("/api/admin/jobs/retry-dead");
      toast.success(`${out.requeued} ${out.requeued === 1 ? "job" : "jobs"} queued again`);
      await queryClient.invalidateQueries({ queryKey: ["jobs"] });
    } catch (e) {
      toast.error(jobError(e));
    } finally {
      setRetryingAll(false);
    }
  }

  return (
    <div className="space-y-3">
      {state === "dead" && (
        <div className="flex justify-end">
          <Button
            variant="outline"
            disabled={retryingAll || !list.data?.length}
            onClick={() => void retryAll()}
          >
            {retryingAll ? (
              <Loader2 aria-hidden className="animate-spin" />
            ) : (
              <RotateCw aria-hidden />
            )}
            Retry all dead
          </Button>
        </div>
      )}
      {list.isPending ? (
        <div role="status" aria-label="Loading jobs" className="space-y-2">
          {Array.from({ length: 3 }, (_, i) => (
            <div key={i} className="h-16 animate-pulse rounded-lg bg-muted" />
          ))}
        </div>
      ) : list.isError ? (
        <div role="alert" className="flex flex-col items-center gap-3 py-14 text-center">
          <p className="font-medium">Could not load jobs</p>
          <Button variant="outline" onClick={() => void list.refetch()}>
            Retry
          </Button>
        </div>
      ) : list.data.length === 0 ? (
        <div className="flex flex-col items-center gap-2 py-14 text-center">
          <span className="flex size-12 items-center justify-center rounded-full bg-muted text-muted-foreground">
            <ListChecks aria-hidden className="size-6" />
          </span>
          <p className="font-medium">{state === "dead" ? "No dead letters" : "Nothing waiting"}</p>
          <p className="text-sm text-muted-foreground">
            {state === "dead"
              ? "Every background job has finished or is still retrying."
              : "The background worker is caught up."}
          </p>
        </div>
      ) : (
        <ul
          aria-label={state === "dead" ? "Dead letters" : "Pending jobs"}
          className="divide-y overflow-hidden rounded-xl bg-card ring-1 ring-foreground/10"
        >
          {list.data.map((job) => (
            <JobRow key={job.id} job={job} state={state} />
          ))}
        </ul>
      )}
    </div>
  );
}

export function JobsPage() {
  const [tab, setTab] = useState<State>("pending");
  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Jobs</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Background work such as image resizing and scheduled publishing. Dead letters ran out of
          retries and need a look.
        </p>
      </div>
      <Tabs value={tab} onValueChange={(v) => setTab(v as State)}>
        <TabsList>
          <TabsTrigger value="pending">Pending</TabsTrigger>
          <TabsTrigger value="dead">Dead letters</TabsTrigger>
        </TabsList>
        <TabsContent value="pending">
          <JobList state="pending" />
        </TabsContent>
        <TabsContent value="dead">
          <JobList state="dead" />
        </TabsContent>
      </Tabs>
    </div>
  );
}
