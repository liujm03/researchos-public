"""Owner's lab-server-only research execution policy; not configurable through env."""

from app.errors import DomainError

LOCAL_RESEARCH_POLICY_CODE = "LAB_SERVER_RESEARCH_ONLY"


def local_research_execution_allowed() -> bool:
    return False


def require_local_research_execution() -> None:
    if not local_research_execution_allowed():
        raise DomainError(
            LOCAL_RESEARCH_POLICY_CODE,
            "本人禁止本机科研实验、模型试运行、训练、评价及仿真；请交接课题组服务器。服务器通道尚未配置。",
            409,
        )


def require_gateway_task_start(kind: str, *, mode: str | None = None) -> None:
    if kind == "experiment_script":
        raise DomainError(
            LOCAL_RESEARCH_POLICY_CODE,
            "实验脚本任务不能在本机启动。可准备代码与服务器交接材料；研究执行只在课题组服务器。",
            409,
        )
    if mode == "workspace_write":
        raise DomainError(
            "CODEX_DIRECT_WORKSPACE_WRITE_RETIRED",
            "模型不能直接修改工作区或执行代码。请使用无执行工具的Patch建议，再通过受限应用流程修改本人代码。",
            409,
        )


def require_gateway_model_turn(
    kind: str, *, mode: str | None = None, no_execution_verified: bool = False
) -> None:
    require_gateway_task_start(kind, mode=mode)
    if no_execution_verified is not True:
        raise DomainError(
            "CODEX_NO_EXECUTION_POLICY_UNVERIFIED",
            "当前任务尚未绑定经验证的无执行工具协议；不会启动旧SDK工具任务。代码改进须采用无工具Patch数据与受控应用。",
            409,
        )
