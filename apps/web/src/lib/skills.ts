import type { components } from "./generated";

export type SkillCapability =
  components["schemas"]["SkillDiscoveryCapabilityOut"];
export type SkillDiscovery = components["schemas"]["SkillDiscoveryOut"];
export type SkillCandidate = components["schemas"]["SkillCandidateOut"];
export type SkillDiscoverRequest =
  components["schemas"]["SkillDiscoveryRequest"];

export const skillConnectionLabels: Record<string, string> = {
  NOT_CONFIGURED: "未配置",
  READY: "发现连接正常",
  DEGRADED: "发现范围受限",
  UNAVAILABLE: "发现连接不可用",
};

export const skillReadLabels: Record<SkillCandidate["read_status"], string> = {
  FILE_VERIFIED: "主文件已读取并校验",
  OUTSIDE_ALLOWED_ROOT: "超出允许读取的目录",
  LINK_REJECTED: "链接路径未读取",
  NOT_FOUND: "主文件不存在",
  TOO_LARGE: "主文件超出大小限制",
  INVALID_UTF8: "主文件不是有效 UTF-8",
  READ_ERROR: "主文件读取失败",
};
