import { skillReadLabels, type SkillCandidate } from "@/lib/skills";

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-[var(--muted)]">{label}</dt>
      <dd className="mt-1 break-all">{value}</dd>
    </div>
  );
}

export function SkillCandidateCard({ skill }: { skill: SkillCandidate }) {
  const dependencies = skill.declared_dependencies || [];
  return (
    <li
      className="rounded-lg border border-[var(--border)] p-4"
      data-testid="skill-candidate"
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <h3 className="break-all font-semibold">{skill.name}</h3>
        <span className="text-xs text-[var(--muted)]">
          {skill.enabled ? "运行时已启用" : "运行时未启用"} · 已被原生发现 ·
          未建立 READY 绑定
        </span>
      </div>
      <p className="mt-2 whitespace-pre-wrap break-words text-sm leading-6 text-[var(--muted)]">
        {skill.description.slice(0, 2000) || "未提供描述"}
        {skill.description.length > 2000 && "…（完整描述见详情）"}
      </p>
      <dl className="mt-3 grid gap-3 text-xs sm:grid-cols-3">
        <Field label="作用域" value={skill.scope || "未声明"} />
        <Field label="插件来源" value={skill.plugin_id || "无插件来源标记"} />
        <Field
          label="主文件读取状态"
          value={skillReadLabels[skill.read_status]}
        />
      </dl>
      <p className="mt-3 break-all font-mono text-[11px] text-[var(--muted)]">
        {skill.path}
      </p>
      <details className="mt-3 text-xs">
        <summary className="cursor-pointer text-[var(--accent)]">
          查看 {skill.name} 的来源与审核详情
        </summary>
        <dl className="mt-3 grid gap-3 sm:grid-cols-2">
          <Field label="候选身份 SHA-256" value={skill.identity_sha256} />
          <Field
            label="主文件 SHA-256"
            value={skill.skill_sha256 || "未取得"}
          />
          <Field
            label="主文件大小"
            value={
              skill.skill_size_bytes == null
                ? "未知"
                : `${skill.skill_size_bytes} bytes`
            }
          />
          <Field
            label="主文件核验"
            value={skill.file_verified ? "已核验文件内容" : "尚未核验文件内容"}
          />
          <Field label="信任审查" value={`${skill.trust_review} · 未审查`} />
          <Field label="兼容性审查" value={`${skill.compatibility} · 未审查`} />
          <Field label="探测" value={`${skill.probe} · 未运行`} />
          <Field label="冒烟验证" value={`${skill.smoke_test} · 未运行`} />
        </dl>
        {skill.description.length > 2000 && (
          <p className="mt-3 max-h-64 overflow-auto whitespace-pre-wrap break-words">
            {skill.description}
          </p>
        )}
        <h4 className="mt-4 font-semibold">声明的依赖（未执行或核验）</h4>
        {dependencies.length ? (
          <ul className="mt-2 max-h-64 space-y-3 overflow-auto">
            {dependencies.map((dependency, index) => (
              <li
                key={index}
                className="space-y-1 break-all rounded border border-[var(--border)] p-2"
              >
                <p>
                  {dependency.type} · {dependency.value}
                </p>
                {dependency.command && (
                  <p className="font-mono">命令：{dependency.command}</p>
                )}
                {dependency.transport && <p>传输：{dependency.transport}</p>}
                {dependency.url && <p>地址：{dependency.url}</p>}
                {dependency.description && (
                  <p className="whitespace-pre-wrap">
                    {dependency.description}
                  </p>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-2 text-[var(--muted)]">
            没有声明依赖，不代表已验证无需依赖。
          </p>
        )}
      </details>
    </li>
  );
}
