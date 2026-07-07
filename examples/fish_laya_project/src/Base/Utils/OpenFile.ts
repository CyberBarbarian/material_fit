/**
 * 文件打开工具
 * 右键点击项目资源面板中的文件选择"打开"，或双击文件，使用系统默认程序打开
 */
export class OpenFile {
    @IEditor.onLoad
    static onLoad(): void {
        Editor.extensionManager.addMenuItem("Project/打开", () => {
            OpenFile.openSelectedFile();
        }, {
            visibleTest: () => OpenFile.canOpenSelectedFile(),
            position: "after create"
        } as IEditor.ICustomMenuItemOptions);

        // 注册常见文件扩展名
        const commonExts = [
            "png", "jpg", "jpeg", "tga", "gif", "bmp", "webp", "svg", "ico",
            "txt", "json", "xml", "csv", "md", "log",
            "mp3", "mp4", "wav", "ogg", "avi", "mov",
            "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx",
            "zip", "rar", "7z", "tar", "gz",
            "html", "htm", "css", "js", "ts", "jsx", "tsx",
            "lmat", "lh", "lani", "ls", "lprefab", "lscene"
        ];

        // 双击
        Editor.extensionManager.addFileActions(commonExts, {
            onOpen: async (asset: IEditor.IAssetInfo) => {
                OpenFile.openFile(asset);
            }
        });
    }

    private static openSelectedFile(): void {
        const projectPanel = Editor.panelManager.getPanel("ProjectPanel") as IEditor.IProjectPanel;
        const asset = projectPanel?.getSelectedResource();

        if (!asset) {
            console.log("未选中任何资源");
            return;
        }

        OpenFile.openFile(asset);
    }

    private static canOpenSelectedFile(): boolean {
        const projectPanel = Editor.panelManager.getPanel("ProjectPanel") as IEditor.IProjectPanel;
        const asset = projectPanel?.getSelectedResource();

        if (!asset) {
            return false;
        }

        const fs = IEditor.require("fs");
        const fullPath = Editor.assetDb.getFullPath(asset);

        if (!fs.existsSync(fullPath)) {
            return false;
        }

        const stat = fs.statSync(fullPath);
        return !stat.isDirectory();
    }

    private static openFile(asset: IEditor.IAssetInfo): void {
        // 场景文件在编辑器内打开
        if (asset.ext === "ls") {
            const activeScene = Editor.sceneManager.activeScene;
            // 当前场景需要用 reloadScene
            if (activeScene && activeScene.asset && activeScene.asset.id === asset.id) {
                Editor.sceneManager.reloadScene(activeScene.sceneId);
            } else {
                // 其他场景需要用 Editor.openFile
                Editor.openFile(asset.file);
            }
            return;
        }

        const fs = IEditor.require("fs");
        const fullPath = Editor.assetDb.getFullPath(asset);

        if (!fs.existsSync(fullPath)) {
            console.log("文件不存在:", fullPath);
            return;
        }

        const stat = fs.statSync(fullPath);
        if (stat.isDirectory()) {
            return;
        }

        // 使用系统默认程序打开文件
        const electron = IEditor.require("electron");
        electron.shell.openPath(fullPath).then(() => {
        }).catch((error: any) => {
            console.warn("打开文件失败:", error);
        });
    }
}
