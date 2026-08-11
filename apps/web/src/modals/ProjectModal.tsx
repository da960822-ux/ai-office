import { Dialog } from '../shared';
import type { Project } from '../api';

export function ProjectModal({ projects, projectId, setProjectId, projectPath, setProjectPath, busy, pickProjectFolder, registerProject, onClose }: {
  projects: Project[]; projectId: string; setProjectId: (id: string) => void; projectPath: string; setProjectPath: (value: string) => void;
  busy: string; pickProjectFolder: () => void; registerProject: () => void; onClose: () => void;
}) {
  return <Dialog title="작업 프로젝트" onClose={onClose}>
    <p className="dialog-copy">프로젝트를 연결하면 에이전트가 원본과 분리된 작업공간에서 작업합니다.</p>
    {projects.length > 0 && <div className="project-list">{projects.map(project => <button key={project.id} className={project.id === projectId ? 'selected' : ''} onClick={() => { setProjectId(project.id); onClose(); }}><b>{project.name}</b><small>{project.root_path}</small></button>)}</div>}
    <label>새 프로젝트 폴더</label><div className="dialog-input-row"><input value={projectPath} onChange={event => setProjectPath(event.target.value)} placeholder="C:\\Projects\\my-app" /><button className="text-button picker-button" onClick={pickProjectFolder} disabled={Boolean(busy)}>폴더 선택</button><button className="solid-button" onClick={registerProject} disabled={Boolean(busy)}>{busy || '연결'}</button></div>
  </Dialog>;
}
