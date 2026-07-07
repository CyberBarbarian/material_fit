/**
 * 根据组件类型查找节点
 */
export class FindNodesByComponentType {
    private static readonly filters: Record<string, string> = {
        "查找SkinnedMeshRenderer": "t:SkinnedMeshRenderer",
        "查找MeshRenderer": "t:MeshRenderer",
        "查找2D粒子": "t:ShurikenParticle2DRenderer",
        "查找3D粒子": "t:ShurikenParticleRenderer",
        "查找Animator": "t:Animator",
    };

    @IEditor.onLoad
    static onLoad(): void {
        for (const label of Object.keys(this.filters)) {
            const filterText = this.filters[label];
            Editor.extensionManager.addMenuItem(`Hierarchy-Tool/${label}`, () => {
                Editor.panelManager.postMessage("HierarchyPanel", "findNodes", filterText);
            }, {
                position: "after findScripts"
            } as IEditor.ICustomMenuItemOptions);
        }
    }
}
