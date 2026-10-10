"use client";

import { useRef, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Input, Textarea } from "@/components/ui/input";
import { ErrorState } from "@/components/ui/state";
import { SourceFilePicker } from "./source-file-picker";
import { RegistryVersionPicker } from "./registry-version-picker";
import type { components } from "@/lib/generated";

type Version = components["schemas"]["BaselineVersionOut"];
type Create = components["schemas"]["BaselineVersionCreate"];
type File = components["schemas"]["BaselineSourceFileChoice"];
type Asset = components["schemas"]["BaselineAssetCreate"];
type Dataset = components["schemas"]["BaselineDatasetCreate"];
type DatasetVersion = components["schemas"]["DatasetVersionOut"];
type Material = {
  declaration: Asset;
  file: File | components["schemas"]["BaselineAssetOut"];
};
type DataDeclaration = { declaration: Dataset; label: string };
export const assetLabels: Record<Asset["role"], string> = {
  CODE: "源码",
  CONFIG: "运行配置",
  ENVIRONMENT_LOCK: "环境锁",
  EVALUATOR: "评价入口",
  WEIGHTS: "权重",
  DATA: "数据文件",
  SPLIT_MANIFEST: "数据划分清单",
};
const selectClass =
  "h-9 w-full rounded border border-[var(--border)] bg-[var(--background)] px-2 text-sm";

export function BaselineVersionEditor({
  projectId,
  parent,
  initialJobId,
  available,
  newBaselineName,
  onNewBaselineName,
  onSave,
}: {
  projectId: string;
  parent: Version | null;
  initialJobId?: string;
  available: boolean;
  newBaselineName: string | null;
  onNewBaselineName: (name: string) => void;
  onSave: (body: Create, name: string | null) => Promise<void>;
}) {
  const [versionName, setVersionName] = useState("");
  const [purpose, setPurpose] = useState(parent?.purpose ?? "");
  const [notes, setNotes] = useState(parent?.notes ?? "");
  const [mode, setMode] = useState<Create["weight_mode"]>(
    parent?.weight_mode ?? "PRETRAINED",
  );
  const [modelVersionId, setModelVersionId] = useState(
    parent?.model_version_id ?? "",
  );
  const [dataCandidate, setDataCandidate] = useState<DatasetVersion | null>(
    null,
  );
  const [license, setLicense] = useState("");
  const [usage, setUsage] = useState("");
  const [data, setData] = useState<DataDeclaration[]>(
    parent?.datasets.map((item) => ({
      declaration: {
        dataset_version_id: item.dataset_version_id,
        license_confirmation: item.license_confirmation,
        usage_scope: item.usage_scope,
      },
      label: `${item.dataset_name} · ${item.dataset_version}`,
    })) ?? [],
  );
  const [role, setRole] = useState<Asset["role"]>("CODE");
  const [assetDataVersion, setAssetDataVersion] = useState("");
  const [materials, setMaterials] = useState<Material[]>(
    parent?.assets.map((file) => ({
      declaration: {
        role: file.role,
        source_file_id: file.source_file_id,
        dataset_version_id: file.dataset_version_id,
      },
      file,
    })) ?? [],
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const busyRef = useRef(false);
  function addFile(file: File) {
    const declaration: Asset = {
      role,
      source_file_id: file.source_file_id,
      dataset_version_id: ["DATA", "SPLIT_MANIFEST"].includes(role)
        ? assetDataVersion || null
        : null,
    };
    if (
      materials.some(
        (item) =>
          item.declaration.role === declaration.role &&
          item.declaration.source_file_id === file.source_file_id &&
          item.declaration.dataset_version_id ===
            declaration.dataset_version_id,
      )
    ) {
      setMessage("该文件与角色已在声明中，未重复添加。");
      return;
    }
    if (materials.length >= 1000) {
      setError("单版本最多声明 1000 个材料条目。");
      return;
    }
    setMaterials((old) => [...old, { declaration, file }]);
    setMessage(`已声明 ${assetLabels[role]}：${file.path}`);
  }
  function addDataset() {
    if (!dataCandidate || !license.trim() || !usage.trim()) return;
    if (
      data.some(
        (item) => item.declaration.dataset_version_id === dataCandidate.id,
      )
    ) {
      setMessage("此数据版本已声明，请修改既有许可用途信息。");
      return;
    }
    setData((old) => [
      ...old,
      {
        declaration: {
          dataset_version_id: dataCandidate.id,
          license_confirmation: license,
          usage_scope: usage,
        },
        label: `数据集版本 ${dataCandidate.version}`,
      },
    ]);
    setLicense("");
    setUsage("");
    setDataCandidate(null);
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busyRef.current || !available) return;
    busyRef.current = true;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const body: Create = {
        version: versionName,
        parent_version_id: parent?.id ?? null,
        expected_parent_sha256: parent?.sha256 ?? null,
        model_version_id: modelVersionId || null,
        paper_id: parent?.paper_id ?? null,
        weight_mode: mode,
        purpose: purpose || null,
        notes: notes || null,
        assets: materials.map((item) => item.declaration),
        datasets: data.map((item) => item.declaration),
      };
      await onSave(body, newBaselineName);
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "基线版本登记失败，所选材料与说明已保留。",
      );
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }
  return (
    <form
      onSubmit={submit}
      className="space-y-4 rounded border border-[var(--border)] p-4"
      aria-label="固定基线版本登记"
    >
      <h2 className="text-lg font-semibold">
        {parent ? "基于已有版本登记新版本" : "登记固定基线版本"}
      </h2>
      <p className="text-xs leading-5 text-[var(--muted)]">
        所选登记、来源与文件角色将固定成新版本。缺材料也可保存 CATALOGED
        草稿；材料完整性由后续显式核查决定。
      </p>
      {parent && (
        <div className="space-y-1 text-xs">
          <p>父版本：{parent.version}</p>
          <details>
            <summary className="cursor-pointer">父版本与哈希</summary>
            <p className="break-all font-mono">{parent.sha256}</p>
          </details>
        </div>
      )}
      {error && <ErrorState message={error} />}
      {message && (
        <p role="status" className="text-xs text-[var(--accent)]">
          {message}
        </p>
      )}
      <fieldset disabled={busy || !available} className="space-y-4">
        <div className="grid gap-3 md:grid-cols-2">
          {newBaselineName !== null && (
            <label className="space-y-1 text-xs">
              基线名称
              <Input
                required
                maxLength={240}
                aria-label="基线名称"
                value={newBaselineName}
                onChange={(event) => onNewBaselineName(event.target.value)}
              />
            </label>
          )}
          <label className="space-y-1 text-xs">
            版本名称
            <Input
              required
              maxLength={120}
              aria-label="基线版本名称"
              value={versionName}
              onChange={(event) => setVersionName(event.target.value)}
              placeholder="例如 v1-rgbt-baseline"
            />
          </label>
          <label className="space-y-1 text-xs">
            权重模式
            <select
              aria-label="基线权重模式"
              className={selectClass}
              value={mode}
              onChange={(event) =>
                setMode(event.target.value as Create["weight_mode"])
              }
            >
              <option value="PRETRAINED">使用预训练权重</option>
              <option value="FROM_SCRATCH">从头训练声明</option>
            </select>
          </label>
        </div>
        <label className="block space-y-1 text-xs">
          用途与目标
          <Textarea
            aria-label="基线用途与目标"
            maxLength={20000}
            value={purpose}
            onChange={(event) => setPurpose(event.target.value)}
          />
        </label>
        <RegistryVersionPicker
          kind="models"
          value={modelVersionId}
          disabled={busy}
          onChange={(version) => setModelVersionId(version?.id ?? "")}
        />
        <section
          className="space-y-3 rounded border border-[var(--border)] p-3"
          aria-label="数据版本与许可声明"
        >
          <RegistryVersionPicker
            kind="datasets"
            value={dataCandidate?.id ?? ""}
            disabled={busy}
            onChange={(version) =>
              setDataCandidate(
                version && "dataset_id" in version ? version : null,
              )
            }
          />
          <label className="block space-y-1 text-xs">
            数据许可确认
            <Textarea
              aria-label="数据许可确认"
              maxLength={4000}
              value={license}
              onChange={(event) => setLicense(event.target.value)}
              placeholder="记录已核对的许可及使用条件"
            />
          </label>
          <label className="block space-y-1 text-xs">
            数据使用范围
            <Textarea
              aria-label="数据使用范围"
              maxLength={4000}
              value={usage}
              onChange={(event) => setUsage(event.target.value)}
              placeholder="本项目训练、验证、测试与分享范围"
            />
          </label>
          <Button
            type="button"
            size="sm"
            variant="secondary"
            disabled={
              !dataCandidate ||
              !license.trim() ||
              !usage.trim() ||
              data.length >= 100
            }
            onClick={addDataset}
          >
            加入此数据版本与用途声明
          </Button>
          {data.map((item, index) => (
            <div
              key={item.declaration.dataset_version_id}
              className="space-y-2 rounded border border-[var(--border)] p-3 text-xs"
            >
              <p className="font-medium">{item.label}</p>
              <label className="block">
                许可确认
                <Textarea
                  aria-label={`已声明数据 ${index + 1} 许可确认`}
                  required
                  maxLength={4000}
                  value={item.declaration.license_confirmation}
                  onChange={(event) =>
                    setData((old) =>
                      old.map((row, at) =>
                        at === index
                          ? {
                              ...row,
                              declaration: {
                                ...row.declaration,
                                license_confirmation: event.target.value,
                              },
                            }
                          : row,
                      ),
                    )
                  }
                />
              </label>
              <label className="block">
                使用范围
                <Textarea
                  aria-label={`已声明数据 ${index + 1} 使用范围`}
                  required
                  maxLength={4000}
                  value={item.declaration.usage_scope}
                  onChange={(event) =>
                    setData((old) =>
                      old.map((row, at) =>
                        at === index
                          ? {
                              ...row,
                              declaration: {
                                ...row.declaration,
                                usage_scope: event.target.value,
                              },
                            }
                          : row,
                      ),
                    )
                  }
                />
              </label>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                aria-label={`移除数据声明 ${item.label}`}
                onClick={() => {
                  setData((old) => old.filter((_, at) => at !== index));
                  setMaterials((old) =>
                    old.map((row) =>
                      row.declaration.dataset_version_id ===
                      item.declaration.dataset_version_id
                        ? {
                            ...row,
                            declaration: {
                              ...row.declaration,
                              dataset_version_id: null,
                            },
                          }
                        : row,
                    ),
                  );
                }}
              >
                移除此版本声明
              </Button>
            </div>
          ))}
        </section>
        <section className="space-y-3" aria-label="必需材料声明">
          <div className="grid gap-3 md:grid-cols-2">
            <label className="space-y-1 text-xs">
              新材料的角色
              <select
                aria-label="新材料的角色"
                className={selectClass}
                value={role}
                onChange={(event) =>
                  setRole(event.target.value as Asset["role"])
                }
              >
                {Object.entries(assetLabels).map(([key, label]) => (
                  <option key={key} value={key}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            {["DATA", "SPLIT_MANIFEST"].includes(role) && (
              <label className="space-y-1 text-xs">
                绑定已声明数据版本
                <select
                  aria-label="材料关联的数据版本"
                  className={selectClass}
                  value={assetDataVersion}
                  onChange={(event) => setAssetDataVersion(event.target.value)}
                >
                  <option value="">未绑定，登记时保留缺口</option>
                  {data.map((item) => (
                    <option
                      key={item.declaration.dataset_version_id}
                      value={item.declaration.dataset_version_id}
                    >
                      {item.label}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </div>
          <SourceFilePicker
            projectId={projectId}
            initialJobId={initialJobId}
            disabled={busy || materials.length >= 1000}
            onAdd={addFile}
          />
          <h3 className="text-sm font-medium">
            已声明必需材料 · {materials.length} 项
          </h3>
          {materials.length ? (
            <ul className="space-y-2">
              {materials.map((item, index) => (
                <li
                  key={`${item.declaration.role}:${item.declaration.source_file_id}:${item.declaration.dataset_version_id}`}
                  className="space-y-1 rounded border border-[var(--border)] p-3 text-xs"
                >
                  <p className="break-all font-medium">
                    {assetLabels[item.declaration.role]} · {item.file.path}
                  </p>
                  <p className="break-all font-mono">{item.file.sha256}</p>
                  <p>
                    {item.file.size_bytes.toLocaleString("zh-CN")} 字节
                    {item.declaration.dataset_version_id
                      ? ` · ${data.find((row) => row.declaration.dataset_version_id === item.declaration.dataset_version_id)?.label ?? "数据版本待核对"}`
                      : ""}
                  </p>
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    aria-label={`移除材料 ${index + 1} ${item.file.path}`}
                    onClick={() =>
                      setMaterials((old) => old.filter((_, at) => at !== index))
                    }
                  >
                    移除材料声明
                  </Button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-xs text-[var(--muted)]">
              尚未声明文件，登记后将显示材料缺口。
            </p>
          )}
        </section>
        <label className="block space-y-1 text-xs">
          本人检查说明
          <Textarea
            aria-label="本人检查说明"
            maxLength={40000}
            value={notes}
            onChange={(event) => setNotes(event.target.value)}
            placeholder="记录已有材料的理解、限制与待核对项；不代替程序观察或科学验证"
          />
        </label>
        <p className="text-xs text-[var(--muted)]">
          {mode === "PRETRAINED"
            ? "预训练模式需要实际权重材料；缺失会保留缺口。"
            : "从头训练是本版本的初始化声明，不启动训练。"}{" "}
          材料登记不授予代码执行或科学资格。
        </p>
        <Button
          type="submit"
          disabled={
            busy ||
            !versionName.trim() ||
            (newBaselineName !== null && !newBaselineName.trim())
          }
        >
          {busy ? "登记中…" : "登记固定版本（不运行）"}
        </Button>
      </fieldset>
    </form>
  );
}
