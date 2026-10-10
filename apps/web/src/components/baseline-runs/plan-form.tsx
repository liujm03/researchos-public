"use client";
import { useRef, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ErrorState } from "@/components/ui/state";
import type { components } from "@/lib/generated";
type Version = components["schemas"]["BaselineVersionOut"];
type Create = components["schemas"]["BaselineRunPlanCreate"];
type Plan = components["schemas"]["BaselineRunPlanOut"];
type Limits = components["schemas"]["BaselineRunLimitsIn"];
const defaults: Limits = {
  timeout_seconds: 120,
  cpu_millicores: 1000,
  memory_bytes: 536870912,
  pids: 32,
  max_input_bytes: 268435456,
  max_input_files: 1000,
  max_log_bytes: 1048576,
  max_output_bytes: 33554432,
  max_output_files: 100,
};
const labels: Record<keyof Limits, string> = {
  timeout_seconds: "运行时间上限（秒）",
  cpu_millicores: "CPU 上限（毫核，1000=1核）",
  memory_bytes: "内存上限（字节）",
  pids: "进程数上限",
  max_input_bytes: "输入字节上限",
  max_input_files: "输入文件数上限",
  max_log_bytes: "日志字节上限",
  max_output_bytes: "输出字节上限",
  max_output_files: "输出文件数上限",
};
const bounds: Record<keyof Limits, [number, number]> = {
  timeout_seconds: [1, 1800],
  cpu_millicores: [100, 4000],
  memory_bytes: [67108864, 8589934592],
  pids: [8, 256],
  max_input_bytes: [1, 1073741824],
  max_input_files: [1, 1000],
  max_log_bytes: [1024, 8388608],
  max_output_bytes: [1024, 268435456],
  max_output_files: [1, 1000],
};
const selectClass =
  "h-9 w-full rounded border border-[var(--border)] bg-[var(--background)] px-2 text-sm";
function localExpiry() {
  const date = new Date(Date.now() + 24 * 60 * 60 * 1000);
  date.setMinutes(date.getMinutes() - date.getTimezoneOffset());
  return date.toISOString().slice(0, 16);
}

export function BaselineRunPlanForm({
  version,
  initial,
  onSave,
}: {
  version: Version;
  initial?: Plan | null;
  onSave: (body: Create) => Promise<void>;
}) {
  const [entry, setEntry] = useState(initial?.entry_asset_id ?? "");
  const [config, setConfig] = useState(initial?.config_asset_id ?? "");
  const [seed, setSeed] = useState(
    String(initial?.parameters.random_seed ?? 0),
  );
  const [maxJobs, setMaxJobs] = useState(String(initial?.max_jobs ?? 1));
  const [expiry, setExpiry] = useState(localExpiry);
  const [limits, setLimits] = useState<Limits>(initial?.limits ?? defaults);
  const [memoryMiB, setMemoryMiB] = useState(
    String((initial?.limits.memory_bytes ?? defaults.memory_bytes!) / 1048576),
  );
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const busyRef = useRef(false);
  const entries = version.assets.filter(
    (asset) =>
      ["CODE", "EVALUATOR"].includes(asset.role) &&
      asset.path.toLowerCase().endsWith(".py"),
  );
  const configs = version.assets.filter((asset) => asset.role === "CONFIG");
  async function save(event: FormEvent) {
    event.preventDefault();
    if (busyRef.current) return;
    setError("");
    const end = new Date(expiry);
    const parsedSeed = Number(seed),
      parsedJobs = Number(maxJobs),
      memory = Number(memoryMiB) * 1048576;
    if (
      !Number.isFinite(end.getTime()) ||
      !Number.isInteger(parsedSeed) ||
      parsedSeed < 0 ||
      parsedSeed > 4294967295 ||
      !Number.isInteger(parsedJobs) ||
      parsedJobs < 1 ||
      parsedJobs > 20 ||
      !Number.isInteger(memory) ||
      memory < bounds.memory_bytes[0] ||
      memory > bounds.memory_bytes[1]
    ) {
      setError("请核对 seed、有效期、次数和内存范围。");
      return;
    }
    const frozen = { ...limits, memory_bytes: memory };
    for (const key of Object.keys(bounds) as (keyof Limits)[]) {
      const value = frozen[key];
      if (
        value === undefined ||
        !Number.isInteger(value) ||
        value < bounds[key][0] ||
        value > bounds[key][1]
      ) {
        setError(`${labels[key]}超出允许范围。`);
        return;
      }
    }
    busyRef.current = true;
    setBusy(true);
    try {
      await onSave({
        expected_version_sha256: version.sha256,
        material_check_id: version.latest_check?.id ?? null,
        entry_asset_id: entry || null,
        config_asset_id: config || null,
        profile: "PYTHON_SCRIPT_V1",
        parameters: { random_seed: parsedSeed },
        limits: frozen,
        expires_at: end.toISOString(),
        max_jobs: parsedJobs,
      });
    } catch (cause) {
      setError(
        (cause instanceof Error ? cause.message : "运行计划暂未保存") +
          "。所选入口和预算已保留；来源变化时请重新预览新计划。",
      );
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }
  return (
    <form
      aria-label="固定基线运行计划"
      className="space-y-4 rounded border border-[var(--border)] p-4"
      onSubmit={save}
    >
      <h2 className="font-semibold">预览新的有界运行计划</h2>
      <p className="text-xs leading-5 text-[var(--muted)]">
        从已登记材料中选择 Python
        入口与配置。保存预览只固定计划，不批准执行；缺环境或材料可保留 DRAFT
        缺口。
      </p>
      {error && <ErrorState message={error} />}
      <fieldset disabled={busy} className="space-y-4">
        <div className="grid gap-3 md:grid-cols-2">
          <label className="space-y-1 text-xs">
            已登记 Python 入口（CODE / EVALUATOR）
            <select
              className={selectClass}
              aria-label="已登记 Python 入口"
              value={entry}
              onChange={(event) => setEntry(event.target.value)}
            >
              <option value="">暂不选择入口，保留草稿缺口</option>
              {entries.map((asset) => (
                <option key={asset.id} value={asset.id}>
                  {asset.path} · {asset.role}
                </option>
              ))}
            </select>
          </label>
          <label className="space-y-1 text-xs">
            已登记运行配置
            <select
              className={selectClass}
              aria-label="已登记运行配置"
              value={config}
              onChange={(event) => setConfig(event.target.value)}
            >
              <option value="">暂不选择配置</option>
              {configs.map((asset) => (
                <option key={asset.id} value={asset.id}>
                  {asset.path}
                </option>
              ))}
            </select>
          </label>
          <label className="space-y-1 text-xs">
            Random seed
            <Input
              type="number"
              min={0}
              max={4294967295}
              required
              aria-label="运行 random seed"
              value={seed}
              onChange={(event) => setSeed(event.target.value)}
            />
          </label>
          <label className="space-y-1 text-xs">
            授权最多任务数
            <Input
              type="number"
              min={1}
              max={20}
              required
              aria-label="运行授权最多任务数"
              value={maxJobs}
              onChange={(event) => setMaxJobs(event.target.value)}
            />
          </label>
          <label className="space-y-1 text-xs">
            授权有效期
            <Input
              type="datetime-local"
              required
              aria-label="运行授权有效期"
              value={expiry}
              onChange={(event) => setExpiry(event.target.value)}
            />
          </label>
          <label className="space-y-1 text-xs">
            运行时间上限（秒）
            <Input
              type="number"
              min={1}
              max={1800}
              required
              aria-label={labels.timeout_seconds}
              value={limits.timeout_seconds}
              onChange={(event) =>
                setLimits((old) => ({
                  ...old,
                  timeout_seconds: Number(event.target.value),
                }))
              }
            />
          </label>
          <label className="space-y-1 text-xs">
            CPU 上限（毫核，1000=1核）
            <Input
              type="number"
              min={100}
              max={4000}
              required
              aria-label={labels.cpu_millicores}
              value={limits.cpu_millicores}
              onChange={(event) =>
                setLimits((old) => ({
                  ...old,
                  cpu_millicores: Number(event.target.value),
                }))
              }
            />
          </label>
          <label className="space-y-1 text-xs">
            内存上限（MiB）
            <Input
              type="number"
              min={64}
              max={8192}
              required
              aria-label="运行内存上限（MiB）"
              value={memoryMiB}
              onChange={(event) => setMemoryMiB(event.target.value)}
            />
          </label>
        </div>
        <details className="rounded border border-[var(--border)] p-3">
          <summary className="cursor-pointer text-xs">
            高级输入、日志与产物预算
          </summary>
          <div className="mt-3 grid gap-3 md:grid-cols-2">
            {(
              [
                "pids",
                "max_input_bytes",
                "max_input_files",
                "max_log_bytes",
                "max_output_bytes",
                "max_output_files",
              ] as (keyof Limits)[]
            ).map((key) => (
              <label key={key} className="space-y-1 text-xs">
                {labels[key]}
                <Input
                  type="number"
                  required
                  min={bounds[key][0]}
                  max={bounds[key][1]}
                  aria-label={labels[key]}
                  value={limits[key]}
                  onChange={(event) =>
                    setLimits((old) => ({
                      ...old,
                      [key]: Number(event.target.value),
                    }))
                  }
                />
              </label>
            ))}
          </div>
        </details>
        <p className="text-xs text-[var(--muted)]">
          环境镜像、daemon、输入投影和固定 profile
          由服务端核对。此通用入口不授予 SMOKE/PROTOCOL 科研资格。
        </p>
        <Button type="submit" disabled={busy}>
          {busy ? "保存计划中…" : "保存并预览运行计划"}
        </Button>
      </fieldset>
    </form>
  );
}
