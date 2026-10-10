"use client";

import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { ErrorState } from "@/components/ui/state";
import { RegistryField, RemoveRowButton } from "./fields";
import { api } from "@/lib/api";
import type { DatasetVersion, DatasetVersionCreate } from "@/lib/experiments";
import {
  nullableNumber,
  nullableText,
  requiredInteger,
} from "@/lib/experiments";

export function DatasetVersionForm({
  datasetId,
  onCreated,
}: {
  datasetId: string;
  onCreated: (version: DatasetVersion) => void;
}) {
  const [version, setVersion] = useState("");
  const [count, setCount] = useState("");
  const [resolution, setResolution] = useState("");
  const [format, setFormat] = useState("");
  const [manifest, setManifest] = useState("");
  const [classes, setClasses] = useState<{ index: string; name: string }[]>([]);
  const [splits, setSplits] = useState<
    { name: string; count: string; manifest: string }[]
  >([]);
  const [locations, setLocations] = useState<
    { provider: string; uri: string; hint: string }[]
  >([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const body: DatasetVersionCreate = {
        version: version.trim(),
        number_images: nullableNumber(count, "图像数量", true),
        resolution: nullableText(resolution),
        annotation_format: nullableText(format),
        manifest_sha256: nullableText(manifest)?.toLowerCase() ?? null,
        classes: classes.map((row) => ({
          class_index: requiredInteger(row.index, "类别索引"),
          name: row.name.trim(),
        })),
        splits: splits.map((row) => ({
          split_name: row.name.trim(),
          sample_count: nullableNumber(row.count, "划分数量", true),
          manifest_uri: nullableText(row.manifest),
        })),
        locations: locations.map((row) => ({
          storage_provider: row.provider.trim(),
          uri: row.uri.trim(),
          mount_hint: nullableText(row.hint),
        })),
      };
      const saved = await api.post<DatasetVersion>(
        "/datasets/" + datasetId + "/versions",
        body,
      );
      setVersion("");
      setClasses([]);
      setSplits([]);
      setLocations([]);
      setCount("");
      setResolution("");
      setFormat("");
      setManifest("");
      onCreated(saved);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "创建数据集版本失败");
    } finally {
      setBusy(false);
    }
  }
  return (
    <form onSubmit={submit} className="space-y-5">
      {error && <ErrorState message={error} />}
      <fieldset disabled={busy} className="space-y-5">
        <p className="text-xs leading-5 text-[var(--muted)]">
          版本创建后保留原始内容。数据或划分发生变化时登记新版本。
        </p>
        <div className="grid gap-4 sm:grid-cols-2">
          <RegistryField
            label="数据集版本名"
            required
            value={version}
            onChange={(event) => setVersion(event.target.value)}
            maxLength={120}
            placeholder="例如 v1.0-rgbt"
          />
          <RegistryField
            label="图像数量（可空）"
            type="number"
            min={0}
            step={1}
            value={count}
            onChange={(event) => setCount(event.target.value)}
          />
          <RegistryField
            label="分辨率"
            value={resolution}
            onChange={(event) => setResolution(event.target.value)}
            placeholder="例如 1920×1080"
            maxLength={240}
          />
          <RegistryField
            label="标注格式"
            value={format}
            onChange={(event) => setFormat(event.target.value)}
            placeholder="例如 COCO / YOLO / masks"
            maxLength={120}
          />
        </div>
        <RegistryField
          label="数据清单 SHA-256（可空）"
          value={manifest}
          onChange={(event) => setManifest(event.target.value)}
          minLength={64}
          maxLength={64}
          pattern="[a-fA-F0-9]{64}"
        />
        <div className="space-y-3">
          <div className="flex items-center justify-between gap-2">
            <h3 className="text-xs font-semibold">类别</h3>
            <Button
              type="button"
              size="sm"
              variant="secondary"
              onClick={() =>
                setClasses((rows) => [
                  ...rows,
                  { index: String(rows.length), name: "" },
                ])
              }
            >
              添加类别
            </Button>
          </div>
          {classes.map((row, index) => (
            <div
              key={index}
              className="grid grid-cols-[100px_minmax(0,1fr)_auto] items-end gap-2"
            >
              <RegistryField
                label={"类别索引 " + (index + 1)}
                type="number"
                required
                min={0}
                step={1}
                value={row.index}
                onChange={(event) =>
                  setClasses((rows) =>
                    rows.map((item, i) =>
                      i === index
                        ? { ...item, index: event.target.value }
                        : item,
                    ),
                  )
                }
              />
              <RegistryField
                label={"类别名称 " + (index + 1)}
                required
                value={row.name}
                onChange={(event) =>
                  setClasses((rows) =>
                    rows.map((item, i) =>
                      i === index
                        ? { ...item, name: event.target.value }
                        : item,
                    ),
                  )
                }
              />
              <RemoveRowButton
                label={"移除类别 " + (index + 1)}
                onClick={() =>
                  setClasses((rows) => rows.filter((_, i) => i !== index))
                }
              />
            </div>
          ))}
        </div>
        <div className="space-y-3">
          <div className="flex items-center justify-between gap-2">
            <h3 className="text-xs font-semibold">
              Train / Validation / Test 划分
            </h3>
            <Button
              type="button"
              size="sm"
              variant="secondary"
              onClick={() =>
                setSplits((rows) => [
                  ...rows,
                  { name: "", count: "", manifest: "" },
                ])
              }
            >
              添加划分
            </Button>
          </div>
          {splits.map((row, index) => (
            <div
              key={index}
              className="space-y-2 rounded border border-[var(--border)] p-3"
            >
              <div className="grid gap-3 sm:grid-cols-[1fr_1fr_auto] items-end">
                <RegistryField
                  label={"划分名称 " + (index + 1)}
                  required
                  value={row.name}
                  onChange={(event) =>
                    setSplits((rows) =>
                      rows.map((item, i) =>
                        i === index
                          ? { ...item, name: event.target.value }
                          : item,
                      ),
                    )
                  }
                  placeholder="train / validation / test"
                />
                <RegistryField
                  label={"划分样本量 " + (index + 1)}
                  type="number"
                  min={0}
                  step={1}
                  value={row.count}
                  onChange={(event) =>
                    setSplits((rows) =>
                      rows.map((item, i) =>
                        i === index
                          ? { ...item, count: event.target.value }
                          : item,
                      ),
                    )
                  }
                />
                <RemoveRowButton
                  label={"移除划分 " + (index + 1)}
                  onClick={() =>
                    setSplits((rows) => rows.filter((_, i) => i !== index))
                  }
                />
              </div>
              <RegistryField
                label={"划分清单地址 " + (index + 1)}
                value={row.manifest}
                onChange={(event) =>
                  setSplits((rows) =>
                    rows.map((item, i) =>
                      i === index
                        ? { ...item, manifest: event.target.value }
                        : item,
                    ),
                  )
                }
              />
            </div>
          ))}
        </div>
        <div className="space-y-3">
          <div className="flex items-center justify-between gap-2">
            <h3 className="text-xs font-semibold">数据位置</h3>
            <Button
              type="button"
              size="sm"
              variant="secondary"
              onClick={() =>
                setLocations((rows) => [
                  ...rows,
                  { provider: "local", uri: "", hint: "" },
                ])
              }
            >
              添加数据位置
            </Button>
          </div>
          {locations.map((row, index) => (
            <div
              key={index}
              className="space-y-2 rounded border border-[var(--border)] p-3"
            >
              <div className="grid gap-3 sm:grid-cols-[1fr_1fr_auto] items-end">
                <RegistryField
                  label={"存储来源 " + (index + 1)}
                  required
                  value={row.provider}
                  onChange={(event) =>
                    setLocations((rows) =>
                      rows.map((item, i) =>
                        i === index
                          ? { ...item, provider: event.target.value }
                          : item,
                      ),
                    )
                  }
                />
                <RegistryField
                  label={"位置地址 " + (index + 1)}
                  required
                  value={row.uri}
                  onChange={(event) =>
                    setLocations((rows) =>
                      rows.map((item, i) =>
                        i === index
                          ? { ...item, uri: event.target.value }
                          : item,
                      ),
                    )
                  }
                  placeholder="本地路径、NAS 或对象地址"
                />
                <RemoveRowButton
                  label={"移除数据位置 " + (index + 1)}
                  onClick={() =>
                    setLocations((rows) => rows.filter((_, i) => i !== index))
                  }
                />
              </div>
              <RegistryField
                label={"挂载说明 " + (index + 1)}
                value={row.hint}
                onChange={(event) =>
                  setLocations((rows) =>
                    rows.map((item, i) =>
                      i === index
                        ? { ...item, hint: event.target.value }
                        : item,
                    ),
                  )
                }
              />
            </div>
          ))}
        </div>
        <Button type="submit" disabled={busy || !version.trim()}>
          {busy ? "登记中…" : "登记数据集版本"}
        </Button>
      </fieldset>
    </form>
  );
}
