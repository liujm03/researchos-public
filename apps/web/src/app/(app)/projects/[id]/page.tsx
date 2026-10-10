"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { ArrowLeft, ArrowRight, BookOpen, Pencil, Plus } from "lucide-react";

import { ProjectPaperPicker } from "@/components/projects/project-paper-picker";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input, Textarea } from "@/components/ui/input";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state";
import { api, type Project, type ProjectPaper } from "@/lib/api";

type Question = {
  id: string;
  question: string;
  rationale: string | null;
  status: string;
};
type Milestone = {
  id: string;
  title: string;
  due_on: string | null;
  status: string;
};

const stageLabels: Record<string, string> = {
  idea: "研究构想",
  literature_review: "文献阅读",
  problem_definition: "确定问题",
  baseline: "准备基线",
  method: "研究方法",
  experiment: "实验",
  ablation: "消融验证",
  writing: "论文写作",
  submission: "投稿",
  revision: "修回",
  accepted: "接收",
};
const stages = [
  "idea",
  "literature_review",
  "problem_definition",
  "baseline",
  "method",
  "experiment",
  "ablation",
  "writing",
  "submission",
  "revision",
  "accepted",
];

export default function ProjectDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [project, setProject] = useState<Project | null>(null);
  const [questions, setQuestions] = useState<Question[]>([]);
  const [milestones, setMilestones] = useState<Milestone[]>([]);
  const [relatedPapers, setRelatedPapers] = useState<ProjectPaper[]>([]);
  const [editing, setEditing] = useState(false);
  const [editValues, setEditValues] = useState({
    name: "",
    summary: "",
    problem: "",
    motivation: "",
    research_gap: "",
    method_overview: "",
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [questionText, setQuestionText] = useState("");
  const [milestoneTitle, setMilestoneTitle] = useState("");
  const [saving, setSaving] = useState(false);

  const load = useCallback(() => {
    Promise.all([
      api.get<Project>(`/projects/${id}`),
      api.get<Question[]>(`/projects/${id}/questions`),
      api.get<Milestone[]>(`/projects/${id}/milestones`),
      api.get<ProjectPaper[]>(`/projects/${id}/papers`),
    ])
      .then(([projectResult, questionResult, milestoneResult, paperResult]) => {
        setProject(projectResult);
        setQuestions(questionResult);
        setMilestones(milestoneResult);
        setRelatedPapers(paperResult);
        setError("");
        if (!editing)
          setEditValues({
            name: projectResult.name,
            summary: projectResult.summary ?? "",
            problem: projectResult.problem ?? "",
            motivation: projectResult.motivation ?? "",
            research_gap: projectResult.research_gap ?? "",
            method_overview: projectResult.method_overview ?? "",
          });
      })
      .catch((cause) =>
        setError(cause instanceof Error ? cause.message : "无法加载课题"),
      )
      .finally(() => setLoading(false));
  }, [id, editing]);
  useEffect(load, [load]);

  async function addQuestion(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      await api.post(`/projects/${id}/questions`, { question: questionText });
      setQuestionText("");
      load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }
  async function addMilestone(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      await api.post(`/projects/${id}/milestones`, { title: milestoneTitle });
      setMilestoneTitle("");
      load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }
  async function advanceStage(event: FormEvent<HTMLSelectElement>) {
    if (!project) return;
    try {
      const updated = await api.patch<Project>(
        `/projects/${id}`,
        { pipeline_stage: event.currentTarget.value },
        project.version,
      );
      setProject(updated);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "阶段更新失败");
    }
  }
  async function saveProject(event: FormEvent) {
    event.preventDefault();
    if (!project) return;
    setSaving(true);
    setError("");
    try {
      const updated = await api.patch<Project>(
        `/projects/${id}`,
        editValues,
        project.version,
      );
      setProject(updated);
      setEditing(false);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "课题保存失败");
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <LoadingState />;
  if (error && !project) return <ErrorState message={error} onRetry={load} />;
  if (!project) return null;

  const steps = [
    {
      title: "本课题文献",
      href: `/papers?project_id=${id}`,
      detail: "按课题查看全部关联文献和 Zotero 来源文件夹",
    },
    {
      title: "本课题精读笔记",
      href: `/inbox?status=ACCEPTED&project_id=${id}`,
      detail: "按课题查看已接受笔记，切换分组查看其他状态",
    },
    {
      title: "文献推荐",
      href: `/projects/${id}/literature`,
      detail: "核对相关文献并主动采纳",
    },
    {
      title: "研究任务书",
      href: `/projects/${id}/brief`,
      detail: "明确问题与文献依据",
    },
    {
      title: "AI 研究规划",
      href: `/projects/${id}/planning`,
      detail: "选择关注点并批准规划",
    },
    {
      title: "源码资料",
      href: `/projects/${id}/sources`,
      detail: "准备复现所需原始资料",
    },
    {
      title: "基线与复现",
      href: `/projects/${id}/baselines`,
      detail: "登记固定材料版本并核对缺口",
    },
    {
      title: "私有版本",
      href: `/projects/${id}/archive`,
      detail: "保存独立项目版本",
    },
    {
      title: "代码改进",
      href: `/projects/${id}/code-changes`,
      detail: "选定文件生成建议、核对差异并受限应用",
    },
    {
      title: "服务器交接",
      href: `/projects/${id}/handoff`,
      detail: "核对任务书并保存服务器交接包",
    },
    {
      title: "结果与下一轮",
      href: `/projects/${id}/results`,
      detail: "回传结果、审阅结论并形成下一轮任务书",
    },
    {
      title: "科研主张与证据",
      href: `/projects/${id}/evidence`,
      detail: "连接假设、支持与反证，记录适用条件和本人结论",
    },
    {
      title: "科研灵感",
      href: `/ideas?project_id=${id}`,
      detail: "记录问题、文献摘录并形成任务与任务书",
    },
    {
      title: "论文工作区",
      href: `/projects/${id}/publications`,
      detail: "固定证据、编辑骨架与正文，逐版本审阅引用和结论",
    },
  ];
  const nextStep = !relatedPapers.length
    ? {
        title: "关联研究文献",
        href: "#project-papers",
        detail: "选择已收录论文，建立课题的文献依据。",
      }
    : ["idea", "literature_review", "problem_definition"].includes(
          project.pipeline_stage,
        )
      ? steps[3]
      : ["baseline", "method", "experiment", "ablation"].includes(
            project.pipeline_stage,
          )
        ? steps[6]
        : steps[13];
  return (
    <div className="space-y-6">
      <Link
        href="/projects"
        className="inline-flex items-center gap-2 text-xs text-[var(--muted)] hover:text-[var(--accent)]"
      >
        <ArrowLeft className="h-4 w-4" />
        返回课题
      </Link>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="mb-1 text-xs uppercase tracking-[0.18em] text-[var(--accent)]">
            Research project
          </p>
          <h1 className="text-2xl font-semibold">{project.name}</h1>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-[var(--muted)]">
            {project.summary ||
              project.problem ||
              "为课题记录研究问题、动机和文献证据。"}
          </p>
        </div>
        <label className="space-y-1 text-xs text-[var(--muted)]">
          当前阶段
          <select
            value={project.pipeline_stage}
            onChange={advanceStage}
            className="block h-9 rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 text-sm text-[var(--foreground)]"
          >
            {stages.map((stage) => (
              <option key={stage} value={stage}>
                {stageLabels[stage] ?? stage}
              </option>
            ))}
          </select>
        </label>
      </div>
      {error && <ErrorState message={error} onRetry={load} />}
      <Card>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-xs text-[var(--muted)]">
                下一步 · 当前阶段{" "}
                {stageLabels[project.pipeline_stage] ?? project.pipeline_stage}
              </p>
              <h2 className="mt-1 font-semibold">{nextStep.title}</h2>
              <p className="mt-1 text-sm text-[var(--muted)]">
                {nextStep.detail}
              </p>
            </div>
            <Button asChild>
              <Link href={nextStep.href}>
                {nextStep.title}
                <ArrowRight className="h-4 w-4" />
              </Link>
            </Button>
          </div>
          <nav
            aria-label="课题研究步骤"
            className="border-t border-[var(--border)] pt-3"
          >
            <ol className="flex flex-wrap gap-x-5 gap-y-2">
              {steps.map((step, index) => (
                <li key={step.href}>
                  <Link
                    href={step.href}
                    className="text-sm hover:text-[var(--accent)]"
                  >
                    <span
                      aria-hidden="true"
                      className="mr-2 text-xs text-[var(--muted)]"
                    >
                      {index + 1}
                    </span>
                    {step.title}
                  </Link>
                </li>
              ))}
            </ol>
          </nav>
        </CardContent>
      </Card>
      <div className="flex justify-end">
        <Button
          variant="secondary"
          size="sm"
          onClick={() => setEditing(!editing)}
        >
          <Pencil className="h-3.5 w-3.5" />
          {editing ? "取消编辑" : "编辑课题"}
        </Button>
      </div>
      {editing && (
        <Card>
          <CardHeader>
            <h2 className="font-semibold">编辑课题说明</h2>
          </CardHeader>
          <CardContent>
            <form onSubmit={saveProject} className="grid gap-4 md:grid-cols-2">
              <label className="space-y-1.5 text-xs font-medium md:col-span-2">
                课题名称
                <Input
                  required
                  value={editValues.name}
                  onChange={(event) =>
                    setEditValues((value) => ({
                      ...value,
                      name: event.target.value,
                    }))
                  }
                />
              </label>
              {(
                [
                  "summary",
                  "problem",
                  "motivation",
                  "research_gap",
                  "method_overview",
                ] as const
              ).map((key) => (
                <label key={key} className="space-y-1.5 text-xs font-medium">
                  {
                    {
                      summary: "概述",
                      problem: "问题",
                      motivation: "动机",
                      research_gap: "Research Gap",
                      method_overview: "方法概述",
                    }[key]
                  }
                  <Textarea
                    value={editValues[key]}
                    onChange={(event) =>
                      setEditValues((value) => ({
                        ...value,
                        [key]: event.target.value,
                      }))
                    }
                  />
                </label>
              ))}
              <div className="md:col-span-2">
                <Button disabled={saving} type="submit">
                  {saving ? "保存中…" : "保存修改"}
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>
      )}
      {(project.problem ||
        project.motivation ||
        project.research_gap ||
        project.method_overview) && (
        <details className="rounded-md border border-[var(--border)] bg-[var(--surface)]">
          <summary className="cursor-pointer px-4 py-3 text-sm font-medium">
            课题简述
          </summary>
          <dl className="grid gap-4 px-4 pb-4 text-sm md:grid-cols-2">
            {[
              ["问题", project.problem],
              ["研究动机", project.motivation],
              ["研究 Gap", project.research_gap],
              ["方法概述", project.method_overview],
            ]
              .filter(([, text]) => text)
              .map(([label, text]) => (
                <div key={label}>
                  <dt className="font-medium">{label}</dt>
                  <dd className="mt-1 whitespace-pre-wrap text-[var(--muted)]">
                    {text}
                  </dd>
                </div>
              ))}
          </dl>
        </details>
      )}
      <details className="rounded-md border border-[var(--border)] bg-[var(--surface)]">
        <summary className="cursor-pointer px-4 py-3 text-sm font-medium">
          研究问题与里程碑 · {questions.length} 个问题 / {milestones.length}{" "}
          个节点
        </summary>
        <div className="p-4 pt-0">
          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader>
                <h2 className="font-semibold">研究问题</h2>
                <span className="text-xs text-[var(--muted)]">
                  {questions.length} 个
                </span>
              </CardHeader>
              <CardContent>
                <form onSubmit={addQuestion} className="mb-4 flex gap-2">
                  <Input
                    required
                    value={questionText}
                    onChange={(event) => setQuestionText(event.target.value)}
                    placeholder="例如：烟雾遮挡下如何定位导线？"
                  />
                  <Button
                    disabled={saving}
                    type="submit"
                    size="icon"
                    aria-label="添加问题"
                  >
                    <Plus className="h-4 w-4" />
                  </Button>
                </form>
                {questions.length ? (
                  <ul className="space-y-2">
                    {questions.map((question) => (
                      <li
                        key={question.id}
                        className="rounded-md border border-[var(--border)] px-3 py-2 text-sm"
                      >
                        {question.question}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <EmptyState title="尚无研究问题" />
                )}
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <h2 className="font-semibold">里程碑</h2>
                <span className="text-xs text-[var(--muted)]">
                  {milestones.length} 个
                </span>
              </CardHeader>
              <CardContent>
                <form onSubmit={addMilestone} className="mb-4 flex gap-2">
                  <Input
                    required
                    value={milestoneTitle}
                    onChange={(event) => setMilestoneTitle(event.target.value)}
                    placeholder="例如：完成 baseline 复现"
                  />
                  <Button
                    disabled={saving}
                    type="submit"
                    size="icon"
                    aria-label="添加里程碑"
                  >
                    <Plus className="h-4 w-4" />
                  </Button>
                </form>
                {milestones.length ? (
                  <ul className="space-y-2">
                    {milestones.map((milestone) => (
                      <li
                        key={milestone.id}
                        className="rounded-md border border-[var(--border)] px-3 py-2 text-sm"
                      >
                        {milestone.title}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <EmptyState title="尚无里程碑" />
                )}
              </CardContent>
            </Card>
          </div>
        </div>
      </details>
      <Card id="project-papers">
        <CardHeader>
          <div className="flex items-center gap-2">
            <BookOpen className="h-4 w-4 text-[var(--accent)]" />
            <h2 className="font-semibold">关联论文</h2>
          </div>
          <span className="text-xs text-[var(--muted)]">
            {relatedPapers.length} 篇
          </span>
        </CardHeader>
        <CardContent>
          <ProjectPaperPicker
            key={id}
            projectId={id}
            relatedPapers={relatedPapers}
            onLinked={setRelatedPapers}
          />
          {relatedPapers.length ? (
            <ul className="divide-y divide-[var(--border)]">
              {relatedPapers.map((paper) => (
                <li key={`${paper.id}-${paper.role}`} className="py-2 text-sm">
                  <Link
                    href={`/papers/${paper.id}`}
                    className="hover:text-[var(--accent)]"
                  >
                    {paper.title}
                  </Link>
                  <span className="ml-2 text-xs text-[var(--muted)]">
                    {paper.year ?? ""}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState title="还没有关联论文" />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
