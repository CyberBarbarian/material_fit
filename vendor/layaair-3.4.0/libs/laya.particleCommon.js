(function (exports, Laya) {
    'use strict';

    class GradientDataNumber {
        static createConstantData(constantValue) {
            let gradientData = new GradientDataNumber();
            gradientData.add(0, constantValue);
            gradientData.add(1, constantValue);
            return gradientData;
        }
        get _elements() {
            return this._dataBuffer;
        }
        set _elements(value) {
            let currentLength = value.length;
            currentLength = currentLength > 16 ? 16 : currentLength;
            this._currentLength = currentLength;
            this._dataBuffer.set(value.subarray(0, currentLength));
            this._formatData();
        }
        get gradientCount() {
            return this._currentLength / 2;
        }
        constructor() {
            this._currentLength = 0;
            this._dataBuffer = new Float32Array(16);
        }
        _formatData() {
            if (this._currentLength == 16)
                return;
            if (this._currentLength >= 2 && this._elements[this._currentLength - 2] !== 1) {
                this._elements[this._currentLength] = 1;
                this._elements[this._currentLength + 1] = this._elements[this._currentLength - 1];
            }
        }
        add(key, value) {
            if (this._currentLength < 16) {
                if ((this._currentLength === 14) && ((key !== 1))) {
                    key = 1;
                    console.log("GradientDataNumber warning:the eighth key is  be force set to 1.");
                }
                this._elements[this._currentLength++] = key;
                this._elements[this._currentLength++] = value;
            }
            else {
                console.log("GradientDataNumber warning:data count must lessEqual than 8");
            }
        }
        getKeyByIndex(index) {
            return this._elements[index * 2];
        }
        getValueByIndex(index) {
            return this._elements[index * 2 + 1];
        }
        getAverageValue() {
            var total = 0;
            var count = 0;
            for (var i = 0, n = this._currentLength - 2; i < n; i += 2) {
                var subValue = this._elements[i + 1];
                subValue += this._elements[i + 3];
                subValue = subValue * (this._elements[i + 2] - this._elements[i]);
                total += subValue;
                count++;
            }
            return total / count;
        }
        cloneTo(destObject) {
            destObject._currentLength = this._currentLength;
            var destElements = destObject._elements;
            for (var i = 0, n = this._elements.length; i < n; i++)
                destElements[i] = this._elements[i];
        }
        clone() {
            var destGradientDataNumber = new GradientDataNumber();
            this.cloneTo(destGradientDataNumber);
            return destGradientDataNumber;
        }
    }

    exports.ParticleMinMaxGradientMode = void 0;
    (function (ParticleMinMaxGradientMode) {
        ParticleMinMaxGradientMode[ParticleMinMaxGradientMode["Color"] = 0] = "Color";
        ParticleMinMaxGradientMode[ParticleMinMaxGradientMode["Gradient"] = 1] = "Gradient";
        ParticleMinMaxGradientMode[ParticleMinMaxGradientMode["TwoColors"] = 2] = "TwoColors";
        ParticleMinMaxGradientMode[ParticleMinMaxGradientMode["TwoGradients"] = 3] = "TwoGradients";
    })(exports.ParticleMinMaxGradientMode || (exports.ParticleMinMaxGradientMode = {}));
    const color = new Laya.Color;
    const color1 = new Laya.Color;
    class ParticleMinMaxGradient {
        get color() {
            return this.colorMin;
        }
        set color(value) {
            this.colorMin = value;
        }
        get gradient() {
            return this.gradientMin;
        }
        set gradient(value) {
            this.gradientMin = value;
        }
        constructor() {
            this.mode = exports.ParticleMinMaxGradientMode.Color;
            this.colorMin = new Laya.Color(1, 1, 1, 1);
            this.colorMax = new Laya.Color(1, 1, 1, 1);
            this.gradientMin = new Laya.Gradient();
            this.gradientMax = new Laya.Gradient();
        }
        evaluate(time, lerp) {
            switch (this.mode) {
                case exports.ParticleMinMaxGradientMode.Color:
                    return this.color;
                case exports.ParticleMinMaxGradientMode.Gradient:
                    this.gradient.evaluateColorRGB(time, color);
                    return color;
                case exports.ParticleMinMaxGradientMode.TwoColors:
                    color.a = Laya.MathUtil.lerp(this.colorMin.a, this.colorMax.a, lerp);
                    color.r = Laya.MathUtil.lerp(this.colorMin.r, this.colorMax.r, lerp);
                    color.g = Laya.MathUtil.lerp(this.colorMin.g, this.colorMax.g, lerp);
                    color.b = Laya.MathUtil.lerp(this.colorMin.b, this.colorMax.b, lerp);
                    return color;
                case exports.ParticleMinMaxGradientMode.TwoGradients:
                    this.gradientMin.evaluateColorRGB(time, color);
                    this.gradientMax.evaluateColorRGB(time, color1);
                    color.a = Laya.MathUtil.lerp(color.a, color1.a, lerp);
                    color.r = Laya.MathUtil.lerp(color.r, color1.r, lerp);
                    color.g = Laya.MathUtil.lerp(color.g, color1.g, lerp);
                    color.b = Laya.MathUtil.lerp(color.b, color1.b, lerp);
                    return color;
                default:
                    return Laya.Color.WHITE;
            }
        }
        cloneTo(destObject) {
            destObject.mode = this.mode;
            this.colorMin.cloneTo(destObject.colorMin);
            this.colorMax.cloneTo(destObject.colorMax);
            this.gradientMin.cloneTo(destObject.gradientMin);
            this.gradientMax.cloneTo(destObject.gradientMax);
        }
        clone() {
            let res = new ParticleMinMaxGradient();
            this.cloneTo(res);
            return res;
        }
    }

    class ColorOverLifetimeModule {
        constructor() {
            this.enable = true;
            this.color = new ParticleMinMaxGradient();
        }
        cloneTo(destObject) {
            destObject.enable = this.enable;
            this.color.cloneTo(destObject.color);
        }
        clone() {
            var dest = new ColorOverLifetimeModule();
            this.cloneTo(dest);
            return dest;
        }
    }

    exports.ParticleMinMaxCurveMode = void 0;
    (function (ParticleMinMaxCurveMode) {
        ParticleMinMaxCurveMode[ParticleMinMaxCurveMode["Constant"] = 0] = "Constant";
        ParticleMinMaxCurveMode[ParticleMinMaxCurveMode["Curve"] = 1] = "Curve";
        ParticleMinMaxCurveMode[ParticleMinMaxCurveMode["TwoConstants"] = 2] = "TwoConstants";
        ParticleMinMaxCurveMode[ParticleMinMaxCurveMode["TwoCurves"] = 3] = "TwoCurves";
    })(exports.ParticleMinMaxCurveMode || (exports.ParticleMinMaxCurveMode = {}));
    class ParticleMinMaxCurve {
        get constant() {
            return this._constantMax;
        }
        set constant(value) {
            this._constantMax = value;
        }
        get constantMin() {
            return this._constantMin;
        }
        set constantMin(value) {
            this._constantMin = value;
        }
        get constantMax() {
            return this._constantMax;
        }
        set constantMax(value) {
            this._constantMax = value;
        }
        get curve() {
            return this._curveMax;
        }
        set curve(value) {
            this._curveMax = value;
        }
        get curveMin() {
            return this._curveMin;
        }
        set curveMin(value) {
            this._curveMin = value;
        }
        get curveMax() {
            return this._curveMax;
        }
        set curveMax(value) {
            this._curveMax = value;
        }
        constructor() {
            this.mode = exports.ParticleMinMaxCurveMode.Constant;
            this._constantMin = 0;
            this._constantMax = 0;
            this._curveMin = new GradientDataNumber();
            this._curveMax = new GradientDataNumber();
        }
        evaluate(time, lerp) {
            switch (this.mode) {
                case exports.ParticleMinMaxCurveMode.Constant:
                    return this.constant;
                case exports.ParticleMinMaxCurveMode.TwoConstants:
                    return Laya.MathUtil.lerp(this.constantMin, this.constantMax, lerp);
                case exports.ParticleMinMaxCurveMode.Curve:
                case exports.ParticleMinMaxCurveMode.TwoCurves:
                default:
                    return 0;
            }
        }
        destroy() {
        }
        cloneTo(dest) {
            dest.mode = this.mode;
            dest.constantMin = this.constantMin;
            dest.constantMax = this.constantMax;
            dest.curveMin = this.curveMin.clone();
            dest.curveMax = this.curveMax.clone();
        }
        clone() {
            let dest = new ParticleMinMaxCurve();
            this.cloneTo(dest);
            return dest;
        }
    }

    class EmissionBurst {
        constructor() {
            this.time = 0;
            this.count = 30;
        }
        cloneTo(destObject) {
            destObject.time = this.time;
            destObject.count = this.count;
        }
        clone() {
            var dest = new EmissionBurst();
            this.cloneTo(dest);
            return dest;
        }
    }
    class EmissionModule {
        get rateOverTime() {
            return this._rateOverTime;
        }
        set rateOverTime(value) {
            if (typeof value === 'number') {
                this._rateOverTime.mode = exports.ParticleMinMaxCurveMode.Constant;
                this._rateOverTime.constant = value;
            }
            else {
                this._rateOverTime = value;
            }
        }
        get bursts() {
            return this._bursts;
        }
        set bursts(value) {
            this._bursts = value;
            if (value) {
                this._sortedBursts = value.slice().sort((a, b) => a.time - b.time);
            }
            else {
                this._sortedBursts = [];
            }
        }
        constructor() {
            this.enable = true;
            this._rateOverTime = new ParticleMinMaxCurve();
            this._lastPosition = new Laya.Vector3();
            this.rateOverDistance = 0;
            this._emitAccumulator = 0;
            this._sortedBursts = [];
            this._rateOverTime.mode = exports.ParticleMinMaxCurveMode.Constant;
            this._rateOverTime.constant = 10;
        }
        destroy() {
            this._sortedBursts = null;
            this._bursts = null;
        }
        cloneTo(destObject) {
            destObject.enable = this.enable;
            this.rateOverTime.cloneTo(destObject._rateOverTime);
            destObject.rateOverDistance = this.rateOverDistance;
            if (this.bursts) {
                let bursts = [];
                this.bursts.forEach(burst => {
                    bursts.push(burst.clone());
                });
                destObject.bursts = bursts;
            }
        }
        clone() {
            let dest = new EmissionModule();
            this.cloneTo(dest);
            return dest;
        }
    }

    exports.TextureSheetAnimationMode = void 0;
    (function (TextureSheetAnimationMode) {
        TextureSheetAnimationMode[TextureSheetAnimationMode["SingleRow"] = 0] = "SingleRow";
        TextureSheetAnimationMode[TextureSheetAnimationMode["WholeSheet"] = 1] = "WholeSheet";
    })(exports.TextureSheetAnimationMode || (exports.TextureSheetAnimationMode = {}));
    class TextureSheetAnimationModule {
        constructor() {
            this.enable = true;
            this.tiles = new Laya.Vector2(1, 1);
            this.animation = exports.TextureSheetAnimationMode.WholeSheet;
            this.frame = new ParticleMinMaxCurve();
            this.startFrame = new ParticleMinMaxCurve();
            this.cycles = 1;
            this._sheetFrameData = new Laya.Vector4;
        }
        _calculateSheetFrameData() {
            let startFrame = this.startFrame;
            let startIndex = startFrame.constant;
            let frameCount = 0;
            let rowIndex = 0;
            let mode = startFrame.mode;
            switch (mode) {
                case exports.ParticleMinMaxCurveMode.Constant:
                    {
                        startIndex = startFrame.constant;
                        break;
                    }
                case exports.ParticleMinMaxCurveMode.TwoConstants:
                    {
                        startIndex = Math.floor(Math.random() * (startFrame.constantMax - startFrame.constantMin) + startFrame.constantMin);
                        break;
                    }
            }
            switch (this.animation) {
                case exports.TextureSheetAnimationMode.SingleRow:
                    frameCount = this.tiles.x;
                    startIndex = startIndex % frameCount;
                    rowIndex = this.rowIndex;
                    break;
                case exports.TextureSheetAnimationMode.WholeSheet:
                    frameCount = this.tiles.x * this.tiles.y;
                    startIndex = startIndex % frameCount;
                    rowIndex = 0;
                    break;
            }
            this._sheetFrameData.setValue(startIndex, frameCount, rowIndex, 0);
        }
        cloneTo(destObject) {
            destObject.enable = this.enable;
            this.tiles.cloneTo(destObject.tiles);
            destObject.animation = this.animation;
            destObject.rowIndex = this.rowIndex;
            this.frame.cloneTo(destObject.frame);
            this.startFrame.cloneTo(destObject.startFrame);
            destObject.cycles = this.cycles;
        }
        clone() {
            var dest = new TextureSheetAnimationModule();
            this.cloneTo(dest);
            return dest;
        }
    }

    Laya.ClassUtils.regClass("GradientDataNumber", GradientDataNumber);
    Laya.ClassUtils.regClass("ParticleMinMaxGradient", ParticleMinMaxGradient);
    Laya.ClassUtils.regClass("ParticleMinMaxCurve", ParticleMinMaxCurve);
    Laya.ClassUtils.regClass("ColorOverLifetimeModule", ColorOverLifetimeModule);
    Laya.ClassUtils.regClass("EmissionModule", EmissionModule);
    Laya.ClassUtils.regClass("EmissionBurst", EmissionBurst);
    Laya.ClassUtils.regClass("TextureSheetAnimationModule", TextureSheetAnimationModule);

    class ParticleInfo {
        constructor() {
            this.timeIndex = 0;
            this.lifetimeIndex = 0;
        }
    }
    class ParticlePool {
        get particleStride() {
            return this._particleStride;
        }
        get particleByteStride() {
            return this._particleByteStride;
        }
        get activeParticleCount() {
            if (this.activeEndIndex >= this.activeStartIndex) {
                return this.activeEndIndex - this.activeStartIndex;
            }
            else {
                return this._maxCount - this.activeStartIndex + this.activeEndIndex;
            }
        }
        ;
        constructor(maxCount, particleByteStride, particleInfo) {
            this._maxCount = maxCount + 1;
            this._particleStride = particleByteStride / Float32Array.BYTES_PER_ELEMENT;
            this._particleByteStride = particleByteStride;
            this.particleDatas = new Float32Array(this._maxCount * this._particleStride);
            this.particleInfo = particleInfo;
            this.clear();
        }
        clear() {
            this.activeStartIndex = 0;
            this.activeEndIndex = 0;
            this.updateStartIndex = 0;
            this.updateEndIndex = 0;
        }
        retireParticles(totleTime) {
            this.activeStartIndex;
            this.activeEndIndex;
            while (this.activeStartIndex != this.activeEndIndex) {
                let index = this.activeStartIndex * this._particleStride;
                let timeIndex = this.particleInfo.timeIndex + index;
                let particleEmitTime = this.particleDatas[timeIndex];
                let particleAge = totleTime - particleEmitTime;
                let lifetimeIndex = this.particleInfo.lifetimeIndex + index;
                let particleLifetime = this.particleDatas[lifetimeIndex];
                if (particleAge < particleLifetime) {
                    break;
                }
                this.activeStartIndex = (this.activeStartIndex + 1) % this._maxCount;
            }
            this.updateStartIndex = this.updateEndIndex = this.activeEndIndex;
            return;
        }
        addParticleData(data) {
            let index = this.activeEndIndex;
            let offset = index * this._particleStride;
            this.particleDatas.set(data, offset);
            this.activeEndIndex = (this.activeEndIndex + 1) % this._maxCount;
            this.updateEndIndex = this.activeEndIndex;
        }
        destroy() {
            this.clear();
            this.particleDatas = null;
        }
    }

    class ParticleControler {
        constructor() {
            this.time = 0;
            this.totalTime = 0;
            this._lastEmitTime = 0;
            this._emitDistance = 0;
            this._nextBurstIndex = 0;
            this._burstLoopCount = 0;
            this._isEmitting = false;
            this._isPlaying = false;
            this._isPaused = false;
            this._isStopped = true;
        }
        _initParticlePool(maxParticles, particleByteStride, particleInfo) {
            if (this.particlePool) {
                this.particlePool.destroy();
            }
            this.particlePool = new ParticlePool(maxParticles, particleByteStride, particleInfo);
        }
        get isEmitting() {
            return this._isEmitting;
        }
        get isPlaying() {
            return this._isPlaying;
        }
        get isPaused() {
            return this._isPaused;
        }
        get isStopped() {
            return this._isStopped;
        }
        play() {
            this._isEmitting = true;
            this._isPlaying = true;
            this._isPaused = false;
            this._isStopped = false;
        }
        pause() {
            if (this.isPlaying) {
                this._isEmitting = false;
                this._isPlaying = false;
                this._isPaused = true;
                this._isStopped = false;
            }
        }
        stop() {
            this._isEmitting = false;
            this._isPlaying = false;
            this._isPaused = false;
            this._isStopped = true;
            this.clear();
        }
        clear() {
            this.time = 0;
            this.totalTime = 0;
            this._lastEmitTime = 0;
            this._emitDistance = 0;
            this._nextBurstIndex = 0;
            this._burstLoopCount = 0;
            this.particlePool.clear();
        }
        destroy() {
            this.clear();
            this.particlePool.destroy();
            this.particlePool = null;
        }
    }

    exports.ColorOverLifetimeModule = ColorOverLifetimeModule;
    exports.EmissionBurst = EmissionBurst;
    exports.EmissionModule = EmissionModule;
    exports.GradientDataNumber = GradientDataNumber;
    exports.ParticleControler = ParticleControler;
    exports.ParticleInfo = ParticleInfo;
    exports.ParticleMinMaxCurve = ParticleMinMaxCurve;
    exports.ParticleMinMaxGradient = ParticleMinMaxGradient;
    exports.ParticlePool = ParticlePool;
    exports.TextureSheetAnimationModule = TextureSheetAnimationModule;

})(window.Laya = window.Laya || {}, Laya);
//# sourceMappingURL=laya.particleCommon.js.map
