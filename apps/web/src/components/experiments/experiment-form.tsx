"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { Button } from "@/components/ui/button";
import { ErrorState } from "@/components/ui/state";
import { RegistryField, RegistryText } from "@/components/registries/fields";
import { api, type Project, type ProjectQuestion } from "@/lib/api";
import {
  nullableText,
  registryItems,
  projectItems,
  type Experiment,
  type ExperimentCreate,
  type Hypothesis,
  type HypothesisCreate,
} from "@/lib/experiments";

export function ExperimentDesignForm({
  onCreated,
}: {
  onCreated: (experiment: Experiment) => void;
}) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [questions, setQuestions] = useState<ProjectQuestion[]>([]);
  const [hypotheses, setHypotheses] = useState<Hypothesis[]>([]);
  const [projectId, setProjectId] = useState("");
  const [questionId, setQuestionId] = useState("");
  const [hypothesisId, setHypothesisId] = useState("");
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [objective, setObjective] = useState("");
  const [statement, setStatement] = useState("");
  const [testPlan, setTestPlan] = useState("");
  const [busy, setBusy] = useState(false);
  const [hypothesisBusy, setHypothesisBusy] = useState(false);
  const [error, setError] = useState("");
  const [optionsError, setOptionsError] = useState("");
  const optionsGeneration = useRef(0);
  const loadChoices = useCallback(async () => {
    const request = ++optionsGeneration.current;
    try {
      const [projectRows, questionRows, hypothesisRows] = await Promise.all([
        projectItems<Project>("/projects"),
        projectId
          ? api.get<ProjectQuestion[]>("/projects/" + projectId + "/questions")
          : Promise.resolve([]),
        projectId
          ? registryItems<Hypothesis>(
              "/hypotheses?project_id=" +
                projectId +
                (questionId ? "&question_id=" + questionId : ""),
            )
          : Promise.resolve([]),
      ]);
      if (request !== optionsGeneration.current) return;
      setProjects(projectRows);
      setQuestions(questionRows);
      setHypotheses(hypothesisRows);
      setOptionsError("");
    } catch (cause) {
      if (request === optionsGeneration.current)
        setOptionsError(
          cause instanceof Error ? cause.message : "无法读取课题、问题或假设",
        );
    }
  }, [projectId, questionId]);
  useEffect(() => {
    let active = true;
    const controller = optionsGeneration;
    queueMicrotask(() => {
      if (active) void loadChoices();
    });
    return () => {
      active = false;
      controller.current++;
    };
  }, [loadChoices]);
  async function createHypothesis() {
    if (!projectId || !statement.trim()) return;
    setHypothesisBusy(true);
    optionsGeneration.current++;
    setError("");
    try {
      const body: HypothesisCreate = {
        project_id: projectId,
        question_id: nullableText(questionId),
        statement: statement.trim(),
        test_plan: nullableText(testPlan),
      };
      const created = await api.post<Hypothesis>("/hypotheses", body);
      setHypotheses((rows) => [created, ...rows]);
      setHypothesisId(created.id);
      setStatement("");
      setTestPlan("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "建立研究假设失败");
    } finally {
      setHypothesisBusy(false);
    }
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const body: ExperimentCreate = {
        experiment_code: code.trim(),
        name: name.trim(),
        project_id: projectId,
        question_id: nullableText(questionId),
        hypothesis_id: nullableText(hypothesisId),
        objective: nullableText(objective),
      };
      onCreated(await api.post<Experiment>("/experiments", body));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "登记实验设计失败");
    } finally {
      setBusy(false);
    }
  }
  return (
    <form onSubmit={submit} className="space-y-5">
      {error && <ErrorState message={error} />}
      {optionsError && (
        <ErrorState message={optionsError} onRetry={() => void loadChoices()} />
      )}
      <fieldset disabled={busy} className="space-y-5">
        <div className="grid gap-4 sm:grid-cols-2">
          <RegistryField
            label="实验编号"
            required
            value={code}
            onChange={(event) => setCode(event.target.value)}
            placeholder="例如 WF-BASELINE-001"
            maxLength={80}
          />
          <RegistryField
            label="实验名称"
            required
            value={name}
            onChange={(event) => setName(event.target.value)}
            maxLength={240}
          />
          <label className="block space-y-1.5 text-xs font-medium">
            所属课题
            <select
              aria-label="实验所属课题"
              required
              value={projectId}
              onChange={(event) => {
                setProjectId(event.target.value);
                setQuestionId("");
                setHypothesisId("");
                setQuestions([]);
                setHypotheses([]);
              }}
              className="h-10 w-full rounded-md border border-[var(--border)] bg-[var(--background)] px-3 text-sm"
            >
              <option value="">选择课题</option>
              {projects.map((project) => (
                <option key={project.id} value={project.id}>
                  {project.name}
                </option>
              ))}
            </select>
          </label>
          <label className="block space-y-1.5 text-xs font-medium">
            研究问题
            <select
              aria-label="实验研究问题"
              value={questionId}
              onChange={(event) => {
                setQuestionId(event.target.value);
                setHypothesisId("");
              }}
              disabled={!projectId}
              className="h-10 w-full rounded-md border border-[var(--border)] bg-[var(--background)] px-3 text-sm"
            >
              <option value="">未关联</option>
              {questions.map((question) => (
                <option key={question.id} value={question.id}>
                  {question.question}
                </option>
              ))}
            </select>
          </label>
        </div>
        <label className="block space-y-1.5 text-xs font-medium">
          待检验假设
          <select
            aria-label="实验待检验假设"
            value={hypothesisId}
            onChange={(event) => setHypothesisId(event.target.value)}
            disabled={!projectId}
            className="h-10 w-full rounded-md border border-[var(--border)] bg-[var(--background)] px-3 text-sm"
          >
            <option value="">未关联</option>
            {hypotheses.map((hypothesis) => (
              <option key={hypothesis.id} value={hypothesis.id}>
                {hypothesis.statement} · {hypothesis.status}
              </option>
            ))}
          </select>
        </label>
        <details className="rounded border border-[var(--border)] p-3">
          <summary className="cursor-pointer text-xs font-medium">
            建立待检验的研究假设
          </summary>
          <div className="mt-3 space-y-3">
            <RegistryText
              label="假设陈述"
              value={statement}
              onChange={(event) => setStatement(event.target.value)}
              maxLength={10000}
            />
            <RegistryText
              label="检验方案"
              value={testPlan}
              onChange={(event) => setTestPlan(event.target.value)}
              maxLength={10000}
            />
            <Button
              type="button"
              size="sm"
              variant="secondary"
              disabled={hypothesisBusy || !projectId || !statement.trim()}
              onClick={() => void createHypothesis()}
            >
              {hypothesisBusy ? "建立中…" : "建立研究假设"}
            </Button>
          </div>
        </details>
        <RegistryText
          label="实验目标"
          value={objective}
          onChange={(event) => setObjective(event.target.value)}
          maxLength={10000}
        />
        <p className="text-xs leading-5 text-[var(--muted)]">
          实验设计描述要验证的问题；后续运行分别冻结模型、数据集、代码与环境。
        </p>
        <Button
          type="submit"
          disabled={busy || !projectId || !code.trim() || !name.trim()}
        >
          {busy ? "登记中…" : "登记实验设计"}
        </Button>
      </fieldset>
    </form>
  );
}
