"use client";

import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { ErrorState } from "@/components/ui/state";
import { RegistryField, RegistryText } from "./fields";
import { api } from "@/lib/api";
import type {
  Dataset,
  DatasetCreate,
  DatasetPatch,
  ResearchModel,
  ModelCreate,
  ModelPatch,
} from "@/lib/experiments";
import { nullableText } from "@/lib/experiments";

export function RegistryMetadataForm({
  kind,
  record,
  onSaved,
}: {
  kind: "datasets" | "models";
  record?: Dataset | ResearchModel;
  onSaved: (record: Dataset | ResearchModel) => void;
}) {
  const model = record && kind === "models" ? (record as ResearchModel) : null;
  const dataset = record && kind === "datasets" ? (record as Dataset) : null;
  const [name, setName] = useState(record?.name ?? "");
  const [task, setTask] = useState(record?.task ?? "");
  const [modalities, setModalities] = useState(
    record?.modalities?.join(", ") ?? "",
  );
  const [source, setSource] = useState(record?.source ?? "");
  const [license, setLicense] = useState(dataset?.license ?? "");
  const [description, setDescription] = useState(dataset?.description ?? "");
  const [family, setFamily] = useState(model?.family ?? "");
  const [architecture, setArchitecture] = useState(model?.architecture ?? "");
  const [paperId, setPaperId] = useState(model?.paper_id ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const common = {
      name: name.trim(),
      task: task.trim(),
      modalities: [
        ...new Set(
          modalities
            .split(",")
            .map((value) => value.trim().toUpperCase().replace(/\s+/g, "_"))
            .filter(Boolean),
        ),
      ],
      source: nullableText(source),
    };
    try {
      if (kind === "datasets") {
        const body: DatasetCreate | DatasetPatch = {
          ...common,
          license: nullableText(license),
          description: nullableText(description),
        };
        const saved = record
          ? await api.patch<Dataset>("/datasets/" + record.id, body)
          : await api.post<Dataset>("/datasets", body);
        onSaved(saved);
      } else {
        const body: ModelCreate | ModelPatch = {
          ...common,
          family: nullableText(family),
          architecture: nullableText(architecture),
          paper_id: nullableText(paperId),
        };
        const saved = record
          ? await api.patch<ResearchModel>("/models/" + record.id, body)
          : await api.post<ResearchModel>("/models", body);
        onSaved(saved);
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "注册信息保存失败");
    } finally {
      setBusy(false);
    }
  }
  return (
    <form onSubmit={submit} className="space-y-4">
      {error && <ErrorState message={error} />}
      <fieldset disabled={busy} className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <RegistryField
            label={kind === "datasets" ? "数据集名称" : "模型名称"}
            value={name}
            onChange={(event) => setName(event.target.value)}
            required
            maxLength={240}
          />
          <RegistryField
            label="科研任务类型"
            value={task}
            onChange={(event) => setTask(event.target.value)}
            required
            maxLength={120}
            placeholder="例如 Object Detection / Segmentation"
          />
          <RegistryField
            label="输入模态（逗号分隔）"
            value={modalities}
            onChange={(event) => setModalities(event.target.value)}
            maxLength={500}
            placeholder="例如 RGB, IR"
          />
          <RegistryField
            label="来源说明或地址"
            value={source}
            onChange={(event) => setSource(event.target.value)}
            maxLength={2000}
          />
          {kind === "datasets" ? (
            <RegistryField
              label="数据许可"
              value={license}
              onChange={(event) => setLicense(event.target.value)}
              maxLength={240}
            />
          ) : (
            <>
              <RegistryField
                label="模型家族"
                value={family}
                onChange={(event) => setFamily(event.target.value)}
                maxLength={120}
              />
              <RegistryField
                label="关联论文 ID（可选）"
                value={paperId}
                onChange={(event) => setPaperId(event.target.value)}
                placeholder="从论文页面地址中复制 ID"
              />
            </>
          )}
        </div>
        <p className="text-xs leading-5 text-[var(--muted)]">
          常用模态：RGB、IR、RGB-T、RGB-D、LIDAR、POINT_CLOUD、VIDEO、MULTIMODAL、SPAD；也可登记自定义代码。
        </p>
        {kind === "datasets" ? (
          <RegistryText
            label="数据集说明"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            maxLength={10000}
          />
        ) : (
          <RegistryText
            label="架构说明"
            value={architecture}
            onChange={(event) => setArchitecture(event.target.value)}
            maxLength={10000}
          />
        )}
        <Button type="submit" disabled={busy || !name.trim() || !task.trim()}>
          {busy
            ? "保存中…"
            : record
              ? "保存注册信息"
              : kind === "datasets"
                ? "登记数据集"
                : "登记模型"}
        </Button>
      </fieldset>
    </form>
  );
}
