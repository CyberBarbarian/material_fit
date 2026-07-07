/**
 * 选择场景资源文件
 * 在 Hierarchy 面板右键菜单中添加"选择场景资源"选项
 * 类似 Unity 的 "Select Scene Asset" 功能，在项目资源面板中定位到当前场景文件
 */
export class SelectSceneAsset {
    @IEditor.onLoad
    static onLoad(): void {
        Editor.extensionManager.addMenuItem("Hierarchy/选择场景资源", () => {
            SelectSceneAsset.selectSceneAsset();
        }, {
            visibleTest: () => SelectSceneAsset.canSelectSceneAsset(),
            position: "first"
        } as IEditor.ICustomMenuItemOptions);

        Editor.extensionManager.addMenuItem("Hierarchy/撤销场景修改", () => {
            SelectSceneAsset.reloadCurrentScene();
        }, {
            visibleTest: () => SelectSceneAsset.canReloadCurrentScene()
        } as IEditor.ICustomMenuItemOptions);
    }

    /**
     * 检查是否可以选择场景资源
     * 只有当前场景已保存时才允许执行
     */
    private static canSelectSceneAsset(): boolean {
        const scene = Editor.sceneManager.activeScene;
        if (!scene) {
            return false;
        }

        // 场景必须已保存（有关联的资源文件）
        const asset = scene.asset;
        return !!asset && !!asset.id;
    }

    private static canReloadCurrentScene(): boolean {
        const scene = Editor.sceneManager.activeScene;
        return !!scene && !!scene.sceneId;
    }

    /**
     * 在项目资源面板中选中当前场景资源
     */
    private static selectSceneAsset(): void {
        const scene = Editor.sceneManager.activeScene;
        if (!scene) {
            console.log("[SelectSceneAsset] 没有打开的场景");
            return;
        }

        const asset = scene.asset;
        if (!asset || !asset.id) {
            console.log("[SelectSceneAsset] 当前场景尚未保存");
            Editor.alert("当前场景尚未保存，无法定位场景资源文件", "info");
            return;
        }

        // 获取项目资源面板
        const projectPanel = Editor.panelManager.getPanel("ProjectPanel") as IEditor.IProjectPanel;
        if (!projectPanel) {
            console.error("[SelectSceneAsset] 无法获取项目资源面板");
            return;
        }

        // 在项目面板中选中场景资源，并聚焦
        projectPanel.select(asset.id, true);
        console.log(`[SelectSceneAsset] 已定位到场景资源: ${asset.file}`);
    }

    private static reloadCurrentScene(): void {
        const scene = Editor.sceneManager.activeScene;
        if (!scene) {
            console.log("[SelectSceneAsset] 没有打开的场景");
            return;
        }

        Editor.sceneManager.reloadScene(scene.sceneId).catch((error: any) => {
            console.error("[SelectSceneAsset] 还原当前场景修改失败:", error);
        });
    }
}
