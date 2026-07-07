
// import "./Polyfills";
// import { App } from "./App";
// import { Game } from "./Game";

const {regClass} = Laya;

@regClass()
export class Main extends Laya.Script {
    async onAwake(): Promise<void> {
        Laya.stage.addChild(this.owner);

        // await App.init();
        // await Game.init();

    }

    onUpdate(): void {
        // App.update();
    }
}
