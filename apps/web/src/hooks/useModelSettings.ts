import { useState } from 'react';
import { api, type McpConnection, type ModelSettings, type ProviderModel } from '../api';

export const modelRoleLabels: [string, string][] = [
  ['orchestrator', 'NAVI · 전체 조율'], ['development_basic', '기본 개발'], ['complex_design_integration', '복잡 설계 · 통합'],
  ['document_research_test_repeat', '문서 · 조사 · 테스트 · 반복'], ['frontend_cicd_operations', '프론트 · CI/CD · 일반 운영'], ['ui_video_mock_review', 'UI · 영상 Mock 검수'],
  ['multimodal_audio_analysis', '음성 포함 멀티모달 분석'], ['debug_escalation', '2회 이상 실패 · 장기 디버깅'], ['final_completion', '최종 완료 판정'],
];

async function pingApi(): Promise<boolean> {
  try { const result = await api.health(); return Boolean(result.ok); } catch { return false; }
}

/**
 * Model routing, API key, connection status, and MCP connection state +
 * handlers. Exposes raw setters too (setModel/setMcpConnections/setProviderModels)
 * so the app-level bootstrap `load()` can populate this state without
 * duplicating fetch logic.
 */
export function useModelSettings(setError: (message: string) => void, friendlyError: (cause: unknown) => string, setBusy: (message: string) => void) {
  const [model, setModel] = useState<ModelSettings>({ provider: 'openrouter', lead_model: 'deepseek/deepseek-v4-pro', worker_model: 'deepseek/deepseek-v4-flash', role_models: {}, team_overrides: {}, employee_overrides: {}, configured: false });
  const [providerModels, setProviderModels] = useState<ProviderModel[]>([]);
  const [mcpConnections, setMcpConnections] = useState<McpConnection[]>([]);
  const [apiKey, setApiKey] = useState('');
  const [mcpProvider, setMcpProvider] = useState<McpConnection['provider']>('github');
  const [mcpName, setMcpName] = useState('GitHub MCP');
  const [mcpUrl, setMcpUrl] = useState('');
  const [mcpToken, setMcpToken] = useState('');
  const [modelTeamId, setModelTeamId] = useState('application');
  const [modelEmployeeId, setModelEmployeeId] = useState('BUILD');
  const [allRolesModel, setAllRolesModel] = useState('');
  const [apiNickname, setApiNicknameState] = useState(() => localStorage.getItem('ai-office-api-nickname') ?? '');
  const [connectionOk, setConnectionOk] = useState(false);
  const [connectionCheckedAt, setConnectionCheckedAt] = useState<number | null>(null);

  const setApiNickname = (value: string) => { setApiNicknameState(value); localStorage.setItem('ai-office-api-nickname', value); };
  const recheckConnection = () => { setConnectionCheckedAt(Date.now()); void pingApi().then(setConnectionOk); };

  const saveModel = async (onDone: () => void) => {
    setBusy('모델 연결 저장 중');
    try { const saved = await api.saveModelSettings(model.role_models, model.team_overrides, model.employee_overrides, apiKey); setModel(saved); setApiKey(''); onDone(); setError(''); }
    catch (cause) { setError(friendlyError(cause)); }
    finally { setBusy(''); }
  };
  const setRoleModel = (role: string, value: string) => setModel(current => ({ ...current, role_models: { ...current.role_models, [role]: value } }));
  const setModelOverride = (scope: 'team_overrides' | 'employee_overrides', id: string, value: string) => setModel(current => {
    const overrides = { ...current[scope] };
    if (value.trim()) overrides[id] = value.trim(); else delete overrides[id];
    return { ...current, [scope]: overrides };
  });
  const applyModelToAllRoles = () => {
    if (!allRolesModel.trim()) { setError('전체 적용할 모델 ID를 입력해 주세요.'); return; }
    setModel(current => ({ ...current, role_models: Object.fromEntries(modelRoleLabels.map(([role]) => [role, allRolesModel.trim()])) }));
  };
  const saveMcp = async () => {
    if (!mcpUrl.trim()) { setError('MCP 서버 URL을 입력해 주세요.'); return; }
    setBusy('MCP 연결을 저장하는 중');
    try { const saved = await api.saveMcpConnection(mcpProvider, mcpName.trim() || mcpProvider, 'streamable_http', mcpUrl.trim(), mcpToken); setMcpConnections(current => [saved, ...current]); setMcpUrl(''); setMcpToken(''); setError(''); }
    catch (cause) { setError(friendlyError(cause)); }
    finally { setBusy(''); }
  };

  return {
    model, setModel, providerModels, setProviderModels, mcpConnections, setMcpConnections,
    apiKey, setApiKey, mcpProvider, setMcpProvider, mcpName, setMcpName, mcpUrl, setMcpUrl, mcpToken, setMcpToken,
    modelTeamId, setModelTeamId, modelEmployeeId, setModelEmployeeId, allRolesModel, setAllRolesModel,
    apiNickname, setApiNickname, connectionOk, setConnectionOk, connectionCheckedAt, setConnectionCheckedAt,
    recheckConnection, pingApi, saveModel, setRoleModel, setModelOverride, applyModelToAllRoles, saveMcp,
  };
}
