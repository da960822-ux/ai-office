import type { Employee, McpConnection, ProviderModel } from './api';
import { personas } from './personas';
import { Dialog } from './shared';
import { modelRoleLabels, type useModelSettings } from './hooks/useModelSettings';

const featuredModels: ProviderModel[] = [
  { id: 'z-ai/glm-5.2', name: 'GLM-5.2', context_length: 1048576 },
  { id: 'deepseek/deepseek-v4-pro', name: 'DeepSeek V4 Pro', context_length: 1048576 },
  { id: 'deepseek/deepseek-v4-flash', name: 'DeepSeek V4 Flash', context_length: 1048576 },
  { id: 'stepfun/step-3.5-flash', name: 'Step 3.5 Flash 2603', context_length: 262144 },
  { id: 'tencent/hy3', name: 'Tencent HY3', context_length: 262144 },
  { id: 'stepfun/step-3.7-flash', name: 'Step 3.7 Flash', context_length: 262144 },
  { id: 'xiaomi/mimo-v2.5', name: 'MiMo V2.5', context_length: 1048576 },
  { id: 'moonshotai/kimi-k2.7-code', name: 'Kimi K2.7 Code', context_length: 1048576 },
];

function ModelSelect({ listId, value, models, onChange, allowInheritance = false }: { listId: string; value: string; models: ProviderModel[]; onChange: (value: string) => void; allowInheritance?: boolean }) {
  const options = [...featuredModels, ...models.filter(model => !featuredModels.some(featured => featured.id === model.id) && (!model.id.startsWith('openai/') || model.id.startsWith('openai/gpt-5.6')))];
  const featuredIds = new Set(featuredModels.map(model => model.id));
  return <div className="model-picker"><select aria-label={`${listId} 모델 선택`} value={value} onChange={event => onChange(event.target.value)}>{allowInheritance && <option value="">역할별 기본값 사용</option>}{value && <option value={value}>{options.find(model => model.id === value)?.name ?? value}</option>}<optgroup label="권장 역할 모델">{options.filter(model => featuredIds.has(model.id) && model.id !== value).map(model => <option key={model.id} value={model.id}>{model.name}</option>)}</optgroup><optgroup label="OpenRouter 전체 모델">{options.filter(model => !featuredIds.has(model.id) && model.id !== value).map(model => <option key={model.id} value={model.id}>{model.name}</option>)}</optgroup></select><input value={value} onChange={event => onChange(event.target.value)} placeholder={allowInheritance ? '빈 값이면 역할별 기본값 사용' : '직접 모델 ID 입력'} /><small>{allowInheritance ? '선택 해제 또는 빈 값이면 기본값으로 복귀' : '목록 선택 또는 OpenRouter 모델 ID 직접 입력'}</small></div>;
}

type Settings = ReturnType<typeof useModelSettings>;

export function ModelSettingsPanel({ settings, employees, teamNames, busy, onClose }: { settings: Settings; employees: Employee[]; teamNames: Record<string, string>; busy: string; onClose: () => void }) {
  const {
    model, providerModels, apiKey, setApiKey, mcpConnections, mcpProvider, setMcpProvider, mcpName, setMcpName,
    mcpUrl, setMcpUrl, mcpToken, setMcpToken, modelTeamId, setModelTeamId, modelEmployeeId, setModelEmployeeId,
    allRolesModel, setAllRolesModel, apiNickname, setApiNickname, connectionOk, connectionCheckedAt,
    recheckConnection, saveModel, setRoleModel, setModelOverride, applyModelToAllRoles, saveMcp,
  } = settings;

  return <Dialog title="AI 및 연결 설정" onClose={onClose}>
    <p className="dialog-copy">모델 기본값은 <code>registry/model-routing.json</code>에서 관리합니다. 저장한 변경값은 개인 설정 파일에만 적용됩니다. 우선순위는 개인 → 부서 → 역할이며, 2회 이상 실패 또는 장기 추적은 Kimi Code 역할을 사용합니다.</p>
    <h3>역할별 기본 모델</h3><div className="model-routing-grid">{modelRoleLabels.map(([role, label]) => <div key={role} className="model-routing-card"><b>{label}</b><ModelSelect listId={`role-${role}`} value={model.role_models[role] ?? ''} models={providerModels} onChange={value => setRoleModel(role, value)} /></div>)}</div>
    <label>전체 기본 역할 일괄 변경</label><div className="model-bulk-row"><ModelSelect listId="all-role-models" value={allRolesModel} models={providerModels} onChange={setAllRolesModel} /><button className="text-button" onClick={applyModelToAllRoles}>전체 적용</button></div>
    <div className="settings-divider" /><h3>부서별 오버라이드</h3><select value={modelTeamId} onChange={event => setModelTeamId(event.target.value)}>{Object.entries(teamNames).map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select><ModelSelect listId="team-model" value={model.team_overrides[modelTeamId] ?? ''} models={providerModels} allowInheritance onChange={value => setModelOverride('team_overrides', modelTeamId, value)} />
    <h3>개인별 오버라이드</h3><select value={modelEmployeeId} onChange={event => setModelEmployeeId(event.target.value)}>{employees.map(employee => <option key={employee.id} value={employee.id}>{personas[employee.id]?.name ?? employee.id} · {employee.model_assignment?.model ?? '기본 모델'}</option>)}</select><ModelSelect listId="employee-model" value={model.employee_overrides[modelEmployeeId] ?? ''} models={providerModels} allowInheritance onChange={value => setModelOverride('employee_overrides', modelEmployeeId, value)} />
    <label>API 별칭 <small>(이 기기에만 저장, 서버 동기화 안 됨)</small></label><input value={apiNickname} onChange={event => setApiNickname(event.target.value)} placeholder="예: 회사 OpenRouter 키" />
    <label>OpenRouter API 키</label><input type="password" value={apiKey} onChange={event => setApiKey(event.target.value)} placeholder={model.configured ? '새 키 입력 시 교체' : 'sk-or-…'} /><button className="solid-button wide" onClick={() => void saveModel(onClose)} disabled={Boolean(busy)}>{busy || '모델 라우팅 저장'}</button>
    <div className="connection-status-row"><span className={`status-dot ${!model.configured ? 'is-unset' : connectionOk ? 'is-ok' : 'is-down'}`} aria-hidden="true" /><span>{!model.configured ? '키가 등록되지 않았습니다.' : connectionOk ? `${apiNickname || 'OpenRouter'} 연결이 살아있습니다.` : '서버에 연결할 수 없습니다. 실행기를 확인하세요.'}</span><button className="text-button" onClick={recheckConnection}>지금 확인</button></div>
    {connectionCheckedAt && <small className="connection-checked-at">마지막 확인: {new Date(connectionCheckedAt).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}</small>}
    <div className="settings-divider" /><h3>MCP 연결</h3><p className="dialog-copy">GitHub, Google Drive, Notion의 MCP 서버 URL과 토큰을 등록합니다. 이름(별칭)은 여러 연결을 구분하는 용도로, 연결 서버가 제공하는 범위만 에이전트에 노출됩니다.</p><select value={mcpProvider} onChange={event => { const provider = event.target.value as McpConnection['provider']; setMcpProvider(provider); setMcpName(provider === 'github' ? 'GitHub MCP' : provider === 'google-drive' ? 'Google Drive MCP' : provider === 'notion' ? 'Notion MCP' : 'Custom MCP'); }}><option value="github">GitHub</option><option value="google-drive">Google Drive</option><option value="notion">Notion</option><option value="custom">Custom</option></select><label>연결 별칭</label><input value={mcpName} onChange={event => setMcpName(event.target.value)} /><label>MCP 서버 URL</label><input value={mcpUrl} onChange={event => setMcpUrl(event.target.value)} placeholder="https://…/mcp" /><label>토큰</label><input type="password" value={mcpToken} onChange={event => setMcpToken(event.target.value)} placeholder="등록 시 보안 저장" /><button className="solid-button wide" onClick={() => void saveMcp()} disabled={Boolean(busy)}>{busy || 'MCP 연결 저장'}</button>
    {mcpConnections.length ? <div className="connection-list">{mcpConnections.map(item => <div key={item.id} className="connection-list-row"><span className={`status-dot ${['configured', 'connected'].includes(item.status) ? 'is-ok' : 'is-down'}`} aria-hidden="true" /><b>{item.name}</b><small>{item.provider} · {item.status}</small></div>)}</div> : null}
  </Dialog>;
}
