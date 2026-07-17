(function (exports, Laya) {
    'use strict';

    class Burst {
        get time() {
            return this._time;
        }
        get minCount() {
            return this._minCount;
        }
        get maxCount() {
            return this._maxCount;
        }
        constructor(time = 0, minCount = 0, maxCount = 0) {
            this._time = time;
            this._minCount = minCount;
            this._maxCount = maxCount;
        }
        cloneTo(destObject) {
            destObject._time = this._time;
            destObject._minCount = this._minCount;
            destObject._maxCount = this._maxCount;
        }
        clone() {
            var destBurst = new Burst(this._time, this._minCount, this._maxCount);
            this.cloneTo(destBurst);
            return destBurst;
        }
    }

    class GradientColor {
        static createByConstant(constant) {
            var gradientColor = new GradientColor();
            gradientColor._type = 0;
            gradientColor._constant = constant;
            return gradientColor;
        }
        static createByGradient(gradient) {
            var gradientColor = new GradientColor();
            gradientColor._type = 1;
            gradientColor._gradient = gradient;
            return gradientColor;
        }
        static createByRandomTwoConstant(minConstant, maxConstant) {
            var gradientColor = new GradientColor();
            gradientColor._type = 2;
            gradientColor._constantMin = minConstant;
            gradientColor._constantMax = maxConstant;
            return gradientColor;
        }
        static createByRandomTwoGradient(minGradient, maxGradient) {
            var gradientColor = new GradientColor();
            gradientColor._type = 3;
            gradientColor._gradientMin = minGradient;
            gradientColor._gradientMax = maxGradient;
            return gradientColor;
        }
        get type() {
            return this._type;
        }
        get constant() {
            return this._constant;
        }
        get constantMin() {
            return this._constantMin;
        }
        get constantMax() {
            return this._constantMax;
        }
        get gradient() {
            return this._gradient;
        }
        get gradientMin() {
            return this._gradientMin;
        }
        get gradientMax() {
            return this._gradientMax;
        }
        constructor() {
            this._type = 0;
            this._constant = null;
            this._constantMin = null;
            this._constantMax = null;
            this._gradient = null;
            this._gradientMin = null;
            this._gradientMax = null;
        }
        cloneTo(destObject) {
            destObject._type = this._type;
            this._constant.cloneTo(destObject._constant);
            this._constantMin.cloneTo(destObject._constantMin);
            this._constantMax.cloneTo(destObject._constantMax);
            this._gradient.cloneTo(destObject._gradient);
            this._gradientMin.cloneTo(destObject._gradientMin);
            this._gradientMax.cloneTo(destObject._gradientMax);
        }
        clone() {
            var destGradientColor = new GradientColor();
            this.cloneTo(destGradientColor);
            return destGradientColor;
        }
    }

    class ColorOverLifetime {
        get color() {
            return this._color;
        }
        constructor(color) {
            this._color = color;
        }
        cloneTo(destObject) {
            this._color.cloneTo(destObject._color);
            destObject.enable = this.enable;
        }
        clone() {
            var destColor;
            switch (this._color.type) {
                case 0:
                    destColor = GradientColor.createByConstant(this._color.constant.clone());
                    break;
                case 1:
                    destColor = GradientColor.createByGradient(this._color.gradient.clone());
                    break;
                case 2:
                    destColor = GradientColor.createByRandomTwoConstant(this._color.constantMin.clone(), this._color.constantMax.clone());
                    break;
                case 3:
                    destColor = GradientColor.createByRandomTwoGradient(this._color.gradientMin.clone(), this._color.gradientMax.clone());
                    break;
            }
            var destColorOverLifetime = new ColorOverLifetime(destColor);
            destColorOverLifetime.enable = this.enable;
            return destColorOverLifetime;
        }
    }

    class Emission {
        get emissionRate() {
            return this._emissionRate;
        }
        set emissionRate(value) {
            if (value < 0)
                throw new Error("emissionRate value must large or equal than 0.");
            this._emissionRate = value;
        }
        get emissionRateOverDistance() {
            return this._emissionRateOverDistance;
        }
        set emissionRateOverDistance(value) {
            value = Math.max(0, value);
            this._emissionRateOverDistance = value;
        }
        get destroyed() {
            return this._destroyed;
        }
        constructor() {
            this._emissionRate = 10;
            this._emissionRateOverDistance = 0;
            this._destroyed = false;
            this._bursts = [];
        }
        destroy() {
            this._bursts = null;
            this._destroyed = true;
        }
        getBurstsCount() {
            return this._bursts.length;
        }
        getBurstByIndex(index) {
            return this._bursts[index];
        }
        addBurst(burst) {
            var burstsCount = this._bursts.length;
            if (burstsCount > 0)
                for (var i = 0; i < burstsCount; i++) {
                    if (this._bursts[i].time > burst.time)
                        this._bursts.splice(i, 0, burst);
                }
            this._bursts.push(burst);
        }
        removeBurst(burst) {
            var index = this._bursts.indexOf(burst);
            if (index !== -1) {
                this._bursts.splice(index, 1);
            }
        }
        removeBurstByIndex(index) {
            this._bursts.splice(index, 1);
        }
        clearBurst() {
            this._bursts.length = 0;
        }
        cloneTo(destObject) {
            var destBursts = destObject._bursts;
            destBursts.length = this._bursts.length;
            for (var i = 0, n = this._bursts.length; i < n; i++) {
                var destBurst = destBursts[i];
                if (destBurst)
                    this._bursts[i].cloneTo(destBurst);
                else
                    destBursts[i] = this._bursts[i].clone();
            }
            destObject._emissionRate = this._emissionRate;
            destObject._emissionRateOverDistance = this._emissionRateOverDistance;
            destObject.enable = this.enable;
        }
        clone() {
            var destEmission = new Emission();
            this.cloneTo(destEmission);
            return destEmission;
        }
    }

    class FrameOverTime {
        static createByConstant(constant = 0) {
            var rotationOverLifetime = new FrameOverTime();
            rotationOverLifetime._type = 0;
            rotationOverLifetime._constant = constant;
            return rotationOverLifetime;
        }
        static createByOverTime(overTime) {
            var rotationOverLifetime = new FrameOverTime();
            rotationOverLifetime._type = 1;
            rotationOverLifetime._overTime = overTime;
            return rotationOverLifetime;
        }
        static createByRandomTwoConstant(constantMin = 0, constantMax = 0) {
            var rotationOverLifetime = new FrameOverTime();
            rotationOverLifetime._type = 2;
            rotationOverLifetime._constantMin = constantMin;
            rotationOverLifetime._constantMax = constantMax;
            return rotationOverLifetime;
        }
        static createByRandomTwoOverTime(gradientFrameMin, gradientFrameMax) {
            var rotationOverLifetime = new FrameOverTime();
            rotationOverLifetime._type = 3;
            rotationOverLifetime._overTimeMin = gradientFrameMin;
            rotationOverLifetime._overTimeMax = gradientFrameMax;
            return rotationOverLifetime;
        }
        get type() {
            return this._type;
        }
        get constant() {
            return this._constant;
        }
        get frameOverTimeData() {
            return this._overTime;
        }
        get constantMin() {
            return this._constantMin;
        }
        get constantMax() {
            return this._constantMax;
        }
        get frameOverTimeDataMin() {
            return this._overTimeMin;
        }
        get frameOverTimeDataMax() {
            return this._overTimeMax;
        }
        constructor() {
            this._type = 0;
            this._constant = 0;
            this._overTime = null;
            this._constantMin = 0;
            this._constantMax = 0;
            this._overTimeMin = null;
            this._overTimeMax = null;
        }
        cloneTo(destFrameOverTime) {
            destFrameOverTime._type = this._type;
            destFrameOverTime._constant = this._constant;
            if (this._overTime) {
                if (!destFrameOverTime._overTime)
                    destFrameOverTime._overTime = this._overTime.clone();
                else
                    this._overTime.cloneTo(destFrameOverTime._overTime);
            }
            destFrameOverTime._constantMin = this._constantMin;
            destFrameOverTime._constantMax = this._constantMax;
            if (this._overTimeMin) {
                if (!destFrameOverTime._overTimeMin)
                    destFrameOverTime._overTimeMin = this._overTimeMin.clone();
                else
                    this._overTimeMin.cloneTo(destFrameOverTime._overTimeMin);
            }
            if (this._overTimeMax) {
                if (!destFrameOverTime._overTimeMax)
                    destFrameOverTime._overTimeMax = this._overTimeMax.clone();
                this._overTimeMax.cloneTo(destFrameOverTime._overTimeMax);
            }
        }
        clone() {
            var destFrameOverTime = new FrameOverTime();
            this.cloneTo(destFrameOverTime);
            return destFrameOverTime;
        }
    }

    class GradientAngularVelocity {
        static createByConstant(constant) {
            var gradientAngularVelocity = new GradientAngularVelocity();
            gradientAngularVelocity._type = 0;
            gradientAngularVelocity._separateAxes = false;
            gradientAngularVelocity._constant = constant;
            return gradientAngularVelocity;
        }
        static createByConstantSeparate(separateConstant) {
            var gradientAngularVelocity = new GradientAngularVelocity();
            gradientAngularVelocity._type = 0;
            gradientAngularVelocity._separateAxes = true;
            gradientAngularVelocity._constantSeparate = separateConstant;
            return gradientAngularVelocity;
        }
        static createByGradient(gradient) {
            var gradientAngularVelocity = new GradientAngularVelocity();
            gradientAngularVelocity._type = 1;
            gradientAngularVelocity._separateAxes = false;
            gradientAngularVelocity._gradient = gradient;
            return gradientAngularVelocity;
        }
        static createByGradientSeparate(gradientX, gradientY, gradientZ) {
            var gradientAngularVelocity = new GradientAngularVelocity();
            gradientAngularVelocity._type = 1;
            gradientAngularVelocity._separateAxes = true;
            gradientAngularVelocity._gradientX = gradientX;
            gradientAngularVelocity._gradientY = gradientY;
            gradientAngularVelocity._gradientZ = gradientZ;
            return gradientAngularVelocity;
        }
        static createByRandomTwoConstant(constantMin, constantMax) {
            var gradientAngularVelocity = new GradientAngularVelocity();
            gradientAngularVelocity._type = 2;
            gradientAngularVelocity._separateAxes = false;
            gradientAngularVelocity._constantMin = constantMin;
            gradientAngularVelocity._constantMax = constantMax;
            return gradientAngularVelocity;
        }
        static createByRandomTwoConstantSeparate(separateConstantMin, separateConstantMax) {
            var gradientAngularVelocity = new GradientAngularVelocity();
            gradientAngularVelocity._type = 2;
            gradientAngularVelocity._separateAxes = true;
            gradientAngularVelocity._constantMinSeparate = separateConstantMin;
            gradientAngularVelocity._constantMaxSeparate = separateConstantMax;
            return gradientAngularVelocity;
        }
        static createByRandomTwoGradient(gradientMin, gradientMax) {
            var gradientAngularVelocity = new GradientAngularVelocity();
            gradientAngularVelocity._type = 3;
            gradientAngularVelocity._separateAxes = false;
            gradientAngularVelocity._gradientMin = gradientMin;
            gradientAngularVelocity._gradientMax = gradientMax;
            return gradientAngularVelocity;
        }
        static createByRandomTwoGradientSeparate(gradientXMin, gradientXMax, gradientYMin, gradientYMax, gradientZMin, gradientZMax, gradientWMin, gradientWMax) {
            var gradientAngularVelocity = new GradientAngularVelocity();
            gradientAngularVelocity._type = 3;
            gradientAngularVelocity._separateAxes = true;
            gradientAngularVelocity._gradientXMin = gradientXMin;
            gradientAngularVelocity._gradientXMax = gradientXMax;
            gradientAngularVelocity._gradientYMin = gradientYMin;
            gradientAngularVelocity._gradientYMax = gradientYMax;
            gradientAngularVelocity._gradientZMin = gradientZMin;
            gradientAngularVelocity._gradientZMax = gradientZMax;
            gradientAngularVelocity._gradientWMin = gradientWMin;
            gradientAngularVelocity._gradientWMax = gradientWMax;
            return gradientAngularVelocity;
        }
        get _constantSeparate() {
            return this.__constantSeparate;
        }
        set _constantSeparate(value) {
            this.__constantSeparate = value.clone();
            this._constantXGradientDdata = Laya.GradientDataNumber.createConstantData(value.x);
            this._constantYGradientDdata = Laya.GradientDataNumber.createConstantData(value.y);
            this._constantZGradientDdata = Laya.GradientDataNumber.createConstantData(value.z);
        }
        get _constant() {
            return this.__constant;
        }
        set _constant(value) {
            this.__constant = value;
            this._constantGradientDdata = Laya.GradientDataNumber.createConstantData(value);
        }
        get _constantMin() {
            return this.__constantMin;
        }
        set _constantMin(value) {
            this.__constantMin = value;
            this._constantMinGradientDdata = Laya.GradientDataNumber.createConstantData(value);
        }
        get _constantMax() {
            return this.__constantMax;
        }
        set _constantMax(value) {
            this.__constantMax = value;
            this._constantMaxGradientDdata = Laya.GradientDataNumber.createConstantData(value);
        }
        get _constantMinSeparate() {
            return this.__constantMinSeparate;
        }
        set _constantMinSeparate(value) {
            this.__constantMinSeparate = value.clone();
            this._constantXMinGradientDdata = Laya.GradientDataNumber.createConstantData(value.x);
            this._constantYMinGradientDdata = Laya.GradientDataNumber.createConstantData(value.y);
            this._constantZMinGradientDdata = Laya.GradientDataNumber.createConstantData(value.z);
        }
        get _constantMaxSeparate() {
            return this.__constantMaxSeparate;
        }
        set _constantMaxSeparate(value) {
            this.__constantMaxSeparate = value;
            this._constantXMaxGradientDdata = Laya.GradientDataNumber.createConstantData(value.x);
            this._constantYMaxGradientDdata = Laya.GradientDataNumber.createConstantData(value.y);
            this._constantZMaxGradientDdata = Laya.GradientDataNumber.createConstantData(value.z);
        }
        get type() {
            return this._type;
        }
        get separateAxes() {
            return this._separateAxes;
        }
        get constant() {
            return this._constant;
        }
        get constantSeparate() {
            return this._constantSeparate;
        }
        get gradient() {
            return this._gradient;
        }
        get gradientX() {
            return this._gradientX;
        }
        get gradientY() {
            return this._gradientY;
        }
        get gradientZ() {
            return this._gradientZ;
        }
        get gradientW() {
            return this._gradientW;
        }
        get constantMin() {
            return this._constantMin;
        }
        get constantMax() {
            return this._constantMax;
        }
        get constantMinSeparate() {
            return this._constantMinSeparate;
        }
        get constantMaxSeparate() {
            return this._constantMaxSeparate;
        }
        get gradientMin() {
            return this._gradientMin;
        }
        get gradientMax() {
            return this._gradientMax;
        }
        get gradientXMin() {
            return this._gradientXMin;
        }
        get gradientXMax() {
            return this._gradientXMax;
        }
        get gradientYMin() {
            return this._gradientYMin;
        }
        get gradientYMax() {
            return this._gradientYMax;
        }
        get gradientZMin() {
            return this._gradientZMin;
        }
        get gradientZMax() {
            return this._gradientZMax;
        }
        get gradientWMin() {
            return this._gradientWMin;
        }
        get gradientWMax() {
            return this._gradientWMax;
        }
        constructor() {
            this._type = 0;
            this._separateAxes = false;
            this.__constantSeparate = null;
            this._gradient = null;
            this._gradientX = null;
            this._gradientY = null;
            this._gradientZ = null;
            this._gradientW = null;
            this._constantGradientDdata = null;
            this._constantMinGradientDdata = null;
            this._constantMaxGradientDdata = null;
            this.__constant = 0;
            this.__constantMin = 0;
            this.__constantMax = 0;
            this.__constantMinSeparate = null;
            this.__constantMaxSeparate = null;
            this._constantXGradientDdata = null;
            this._constantYGradientDdata = null;
            this._constantZGradientDdata = null;
            this._constantXMinGradientDdata = null;
            this._constantYMinGradientDdata = null;
            this._constantZMinGradientDdata = null;
            this._constantXMaxGradientDdata = null;
            this._constantYMaxGradientDdata = null;
            this._constantZMaxGradientDdata = null;
            this._gradientMin = null;
            this._gradientMax = null;
            this._gradientXMin = null;
            this._gradientXMax = null;
            this._gradientYMin = null;
            this._gradientYMax = null;
            this._gradientZMin = null;
            this._gradientZMax = null;
            this._gradientWMin = null;
            this._gradientWMax = null;
        }
        cloneTo(destObject) {
            destObject._type = this._type;
            destObject._separateAxes = this._separateAxes;
            destObject._constant = this._constant;
            this._constantSeparate.cloneTo(destObject._constantSeparate);
            this._gradient.cloneTo(destObject._gradient);
            this._gradientX.cloneTo(destObject._gradientX);
            this._gradientY.cloneTo(destObject._gradientY);
            this._gradientZ.cloneTo(destObject._gradientZ);
            destObject._constantMin = this._constantMin;
            destObject._constantMax = this._constantMax;
            this._constantMinSeparate.cloneTo(destObject._constantMinSeparate);
            this._constantMaxSeparate.cloneTo(destObject._constantMaxSeparate);
            this._gradientMin.cloneTo(destObject._gradientMin);
            this._gradientMax.cloneTo(destObject._gradientMax);
            this._gradientXMin.cloneTo(destObject._gradientXMin);
            this._gradientXMax.cloneTo(destObject._gradientXMax);
            this._gradientYMin.cloneTo(destObject._gradientYMin);
            this._gradientYMax.cloneTo(destObject._gradientYMax);
            this._gradientZMin.cloneTo(destObject._gradientZMin);
            this._gradientZMax.cloneTo(destObject._gradientZMax);
        }
        clone() {
            var destGradientAngularVelocity = new GradientAngularVelocity();
            this.cloneTo(destGradientAngularVelocity);
            return destGradientAngularVelocity;
        }
    }

    class GradientDataInt {
        get gradientCount() {
            return this._currentLength / 2;
        }
        constructor() {
            this._currentLength = 0;
            this._curveMin = 0;
            this._curveMax = 1;
            this._elements = new Float32Array(8);
        }
        _formatData() {
            if (this._currentLength == 8)
                return;
            if (this._elements[this._currentLength - 2] !== 1) {
                this._elements[this._currentLength] = 1;
                this._elements[this._currentLength + 1] = this._elements[this._currentLength - 1];
            }
        }
        add(key, value) {
            if (this._currentLength < 8) {
                if ((this._currentLength === 6) && ((key !== 1))) {
                    key = 1;
                    console.log("Warning:the forth key is  be force set to 1.");
                }
                this._elements[this._currentLength++] = key;
                this._elements[this._currentLength++] = value;
            }
            else {
                console.log("Warning:data count must lessEqual than 4");
            }
        }
        cloneTo(destObject) {
            destObject._currentLength = this._currentLength;
            var destElements = destObject._elements;
            for (var i = 0, n = this._elements.length; i < n; i++) {
                destElements[i] = this._elements[i];
            }
        }
        clone() {
            var destGradientDataInt = new GradientDataInt();
            this.cloneTo(destGradientDataInt);
            return destGradientDataInt;
        }
    }

    class GradientSize {
        static createByGradient(gradient) {
            var gradientSize = new GradientSize();
            gradientSize._type = 0;
            gradientSize._separateAxes = false;
            gradientSize._gradient = gradient;
            return gradientSize;
        }
        static createByGradientSeparate(gradientX, gradientY, gradientZ) {
            var gradientSize = new GradientSize();
            gradientSize._type = 0;
            gradientSize._separateAxes = true;
            gradientSize._gradientX = gradientX;
            gradientSize._gradientY = gradientY;
            gradientSize._gradientZ = gradientZ;
            return gradientSize;
        }
        static createByRandomTwoConstant(constantMin, constantMax) {
            var gradientSize = new GradientSize();
            gradientSize._type = 1;
            gradientSize._separateAxes = false;
            gradientSize._constantMin = constantMin;
            gradientSize._constantMax = constantMax;
            return gradientSize;
        }
        static createByRandomTwoConstantSeparate(constantMinSeparate, constantMaxSeparate) {
            var gradientSize = new GradientSize();
            gradientSize._type = 1;
            gradientSize._separateAxes = true;
            gradientSize._constantMinSeparate = constantMinSeparate;
            gradientSize._constantMaxSeparate = constantMaxSeparate;
            return gradientSize;
        }
        static createByRandomTwoGradient(gradientMin, gradientMax) {
            var gradientSize = new GradientSize();
            gradientSize._type = 2;
            gradientSize._separateAxes = false;
            gradientSize._gradientMin = gradientMin;
            gradientSize._gradientMax = gradientMax;
            return gradientSize;
        }
        static createByRandomTwoGradientSeparate(gradientXMin, gradientXMax, gradientYMin, gradientYMax, gradientZMin, gradientZMax) {
            var gradientSize = new GradientSize();
            gradientSize._type = 2;
            gradientSize._separateAxes = true;
            gradientSize._gradientXMin = gradientXMin;
            gradientSize._gradientXMax = gradientXMax;
            gradientSize._gradientYMin = gradientYMin;
            gradientSize._gradientYMax = gradientYMax;
            gradientSize._gradientZMin = gradientZMin;
            gradientSize._gradientZMax = gradientZMax;
            return gradientSize;
        }
        get type() {
            return this._type;
        }
        get separateAxes() {
            return this._separateAxes;
        }
        get gradient() {
            return this._gradient;
        }
        get gradientX() {
            return this._gradientX;
        }
        get gradientY() {
            return this._gradientY;
        }
        get gradientZ() {
            return this._gradientZ;
        }
        get constantMin() {
            return this._constantMin;
        }
        get constantMax() {
            return this._constantMax;
        }
        get constantMinSeparate() {
            return this._constantMinSeparate;
        }
        get constantMaxSeparate() {
            return this._constantMaxSeparate;
        }
        get gradientMin() {
            return this._gradientMin;
        }
        get gradientMax() {
            return this._gradientMax;
        }
        get gradientXMin() {
            return this._gradientXMin;
        }
        get gradientXMax() {
            return this._gradientXMax;
        }
        get gradientYMin() {
            return this._gradientYMin;
        }
        get gradientYMax() {
            return this._gradientYMax;
        }
        get gradientZMin() {
            return this._gradientZMin;
        }
        get gradientZMax() {
            return this._gradientZMax;
        }
        constructor() {
            this._type = 0;
            this._separateAxes = false;
            this._gradient = null;
            this._gradientX = null;
            this._gradientY = null;
            this._gradientZ = null;
            this._constantMin = 0;
            this._constantMax = 0;
            this._constantMinSeparate = null;
            this._constantMaxSeparate = null;
            this._gradientMin = null;
            this._gradientMax = null;
            this._gradientXMin = null;
            this._gradientXMax = null;
            this._gradientYMin = null;
            this._gradientYMax = null;
            this._gradientZMin = null;
            this._gradientZMax = null;
        }
        getMaxSizeInGradient(meshMode = false) {
            var i, n;
            var maxSize = -Number.MAX_VALUE;
            switch (this._type) {
                case 0:
                    if (this._separateAxes) {
                        for (i = 0, n = this._gradientX.gradientCount; i < n; i++)
                            maxSize = Math.max(maxSize, this._gradientX.getValueByIndex(i));
                        for (i = 0, n = this._gradientY.gradientCount; i < n; i++)
                            maxSize = Math.max(maxSize, this._gradientY.getValueByIndex(i));
                        if (meshMode) {
                            for (i = 0, n = this._gradientZ.gradientCount; i < n; i++) {
                                maxSize = Math.max(maxSize, this._gradientZ.getValueByIndex(i));
                            }
                        }
                    }
                    else {
                        for (i = 0, n = this._gradient.gradientCount; i < n; i++)
                            maxSize = Math.max(maxSize, this._gradient.getValueByIndex(i));
                    }
                    break;
                case 1:
                    if (this._separateAxes) {
                        maxSize = Math.max(this._constantMinSeparate.x, this._constantMaxSeparate.x);
                        maxSize = Math.max(maxSize, this._constantMinSeparate.y);
                        if (meshMode) {
                            maxSize = maxSize = Math.max(maxSize, this._constantMaxSeparate.z);
                        }
                    }
                    else {
                        maxSize = Math.max(this._constantMin, this._constantMax);
                    }
                    break;
                case 2:
                    if (this._separateAxes) {
                        for (i = 0, n = this._gradientXMin.gradientCount; i < n; i++)
                            maxSize = Math.max(maxSize, this._gradientXMin.getValueByIndex(i));
                        for (i = 0, n = this._gradientXMax.gradientCount; i < n; i++)
                            maxSize = Math.max(maxSize, this._gradientXMax.getValueByIndex(i));
                        for (i = 0, n = this._gradientYMin.gradientCount; i < n; i++)
                            maxSize = Math.max(maxSize, this._gradientYMin.getValueByIndex(i));
                        for (i = 0, n = this._gradientZMax.gradientCount; i < n; i++)
                            maxSize = Math.max(maxSize, this._gradientZMax.getValueByIndex(i));
                        if (meshMode) {
                            for (i = 0, n = this._gradientZMin.gradientCount; i < n; i++) {
                                maxSize = Math.max(maxSize, this._gradientZMin.getValueByIndex(i));
                            }
                            for (i = 0, n = this._gradientZMax.gradientCount; i < n; i++) {
                                maxSize = Math.max(maxSize, this._gradientZMax.getValueByIndex(i));
                            }
                        }
                    }
                    else {
                        for (i = 0, n = this._gradientMin.gradientCount; i < n; i++)
                            maxSize = Math.max(maxSize, this._gradientMin.getValueByIndex(i));
                        for (i = 0, n = this._gradientMax.gradientCount; i < n; i++)
                            maxSize = Math.max(maxSize, this._gradientMax.getValueByIndex(i));
                    }
                    break;
            }
            return maxSize;
        }
        cloneTo(destObject) {
            destObject._type = this._type;
            destObject._separateAxes = this._separateAxes;
            this._gradient.cloneTo(destObject._gradient);
            this._gradientX.cloneTo(destObject._gradientX);
            this._gradientY.cloneTo(destObject._gradientY);
            this._gradientZ.cloneTo(destObject._gradientZ);
            destObject._constantMin = this._constantMin;
            destObject._constantMax = this._constantMax;
            this._constantMinSeparate.cloneTo(destObject._constantMinSeparate);
            this._constantMaxSeparate.cloneTo(destObject._constantMaxSeparate);
            this._gradientMin.cloneTo(destObject._gradientMin);
            this._gradientMax.cloneTo(destObject._gradientMax);
            this._gradientXMin.cloneTo(destObject._gradientXMin);
            this._gradientXMax.cloneTo(destObject._gradientXMax);
            this._gradientYMin.cloneTo(destObject._gradientYMin);
            this._gradientYMax.cloneTo(destObject._gradientYMax);
            this._gradientZMin.cloneTo(destObject._gradientZMin);
            this._gradientZMax.cloneTo(destObject._gradientZMax);
        }
        clone() {
            var destGradientSize = new GradientSize();
            this.cloneTo(destGradientSize);
            return destGradientSize;
        }
    }

    class GradientVelocity {
        static createByConstant(constant) {
            var gradientVelocity = new GradientVelocity();
            gradientVelocity._type = 0;
            gradientVelocity._constant = constant;
            gradientVelocity._gradientConstantXMin = Laya.GradientDataNumber.createConstantData(constant.x);
            gradientVelocity._gradientConstantYMin = Laya.GradientDataNumber.createConstantData(constant.y);
            gradientVelocity._gradientConstantZMin = Laya.GradientDataNumber.createConstantData(constant.z);
            return gradientVelocity;
        }
        static createByGradient(gradientX, gradientY, gradientZ) {
            var gradientVelocity = new GradientVelocity();
            gradientVelocity._type = 1;
            gradientVelocity._gradientX = gradientX;
            gradientVelocity._gradientY = gradientY;
            gradientVelocity._gradientZ = gradientZ;
            return gradientVelocity;
        }
        static createByRandomTwoConstant(constantMin, constantMax) {
            var gradientVelocity = new GradientVelocity();
            gradientVelocity._type = 2;
            gradientVelocity._constantMin = constantMin;
            gradientVelocity._constantMax = constantMax;
            gradientVelocity._gradientConstantXMin = Laya.GradientDataNumber.createConstantData(constantMin.x);
            gradientVelocity._gradientConstantXMax = Laya.GradientDataNumber.createConstantData(constantMax.x);
            gradientVelocity._gradientConstantYMin = Laya.GradientDataNumber.createConstantData(constantMin.y);
            gradientVelocity._gradientConstantYMax = Laya.GradientDataNumber.createConstantData(constantMax.y);
            gradientVelocity._gradientConstantZMin = Laya.GradientDataNumber.createConstantData(constantMin.z);
            gradientVelocity._gradientConstantZMax = Laya.GradientDataNumber.createConstantData(constantMax.z);
            return gradientVelocity;
        }
        static createByRandomTwoGradient(gradientXMin, gradientXMax, gradientYMin, gradientYMax, gradientZMin, gradientZMax) {
            var gradientVelocity = new GradientVelocity();
            gradientVelocity._type = 3;
            gradientVelocity._gradientXMin = gradientXMin;
            gradientVelocity._gradientXMax = gradientXMax;
            gradientVelocity._gradientYMin = gradientYMin;
            gradientVelocity._gradientYMax = gradientYMax;
            gradientVelocity._gradientZMin = gradientZMin;
            gradientVelocity._gradientZMax = gradientZMax;
            return gradientVelocity;
        }
        get _constant() {
            return this.__constant;
        }
        set _constant(value) {
            this.__constant = value;
            this._gradientConstantX = Laya.GradientDataNumber.createConstantData(value.x);
            this._gradientConstantY = Laya.GradientDataNumber.createConstantData(value.y);
            this._gradientConstantZ = Laya.GradientDataNumber.createConstantData(value.z);
        }
        get _constantMin() {
            return this.__constantMin;
        }
        set _constantMin(value) {
            this.__constantMin = value;
            this._gradientConstantXMin = Laya.GradientDataNumber.createConstantData(value.x);
            this._gradientConstantYMin = Laya.GradientDataNumber.createConstantData(value.y);
            this._gradientConstantZMin = Laya.GradientDataNumber.createConstantData(value.z);
        }
        get _constantMax() {
            return this.__constantMax;
        }
        set _constantMax(value) {
            this.__constantMax = value;
            this._gradientConstantXMax = Laya.GradientDataNumber.createConstantData(value.x);
            this._gradientConstantYMax = Laya.GradientDataNumber.createConstantData(value.y);
            this._gradientConstantZMax = Laya.GradientDataNumber.createConstantData(value.z);
        }
        get type() {
            return this._type;
        }
        get constant() {
            return this._constant;
        }
        get gradientX() {
            return this._gradientX;
        }
        get gradientY() {
            return this._gradientY;
        }
        get gradientZ() {
            return this._gradientZ;
        }
        get constantMin() {
            return this._constantMin;
        }
        get constantMax() {
            return this._constantMax;
        }
        get gradientConstantX() {
            return this._gradientConstantX;
        }
        get gradientConstantY() {
            return this._gradientConstantY;
        }
        get gradientConstantZ() {
            return this._gradientConstantZ;
        }
        get gradientConstantXMin() {
            return this._gradientConstantXMin;
        }
        get gradientConstantXMax() {
            return this._gradientConstantXMax;
        }
        get gradientConstantYMin() {
            return this._gradientConstantYMin;
        }
        get gradientConstantYMax() {
            return this._gradientConstantYMax;
        }
        get gradientConstantZMin() {
            return this._gradientConstantZMin;
        }
        get gradientConstantZMax() {
            return this._gradientConstantZMax;
        }
        get gradientXMin() {
            return this._gradientXMin;
        }
        get gradientXMax() {
            return this._gradientXMax;
        }
        get gradientYMin() {
            return this._gradientYMin;
        }
        get gradientYMax() {
            return this._gradientYMax;
        }
        get gradientZMin() {
            return this._gradientZMin;
        }
        get gradientZMax() {
            return this._gradientZMax;
        }
        constructor() {
            this._type = 0;
            this.__constant = null;
            this.__constantMin = null;
            this.__constantMax = null;
            this._gradientConstantX = null;
            this._gradientConstantY = null;
            this._gradientConstantZ = null;
            this._gradientConstantXMin = null;
            this._gradientConstantXMax = null;
            this._gradientConstantYMin = null;
            this._gradientConstantYMax = null;
            this._gradientConstantZMin = null;
            this._gradientConstantZMax = null;
            this._gradientX = null;
            this._gradientY = null;
            this._gradientZ = null;
            this._gradientXMin = null;
            this._gradientXMax = null;
            this._gradientYMin = null;
            this._gradientYMax = null;
            this._gradientZMin = null;
            this._gradientZMax = null;
        }
        cloneTo(destObject) {
            destObject._type = this._type;
            this._constant.cloneTo(destObject._constant);
            this._gradientX.cloneTo(destObject._gradientX);
            this._gradientY.cloneTo(destObject._gradientY);
            this._gradientZ.cloneTo(destObject._gradientZ);
            this._constantMin.cloneTo(destObject._constantMin);
            this._constantMax.cloneTo(destObject._constantMax);
            this._gradientXMin.cloneTo(destObject._gradientXMin);
            this._gradientXMax.cloneTo(destObject._gradientXMax);
            this._gradientYMin.cloneTo(destObject._gradientYMin);
            this._gradientYMax.cloneTo(destObject._gradientYMax);
            this._gradientZMin.cloneTo(destObject._gradientZMin);
            this._gradientZMax.cloneTo(destObject._gradientZMax);
        }
        clone() {
            var destGradientVelocity = new GradientVelocity();
            this.cloneTo(destGradientVelocity);
            return destGradientVelocity;
        }
    }

    class RotationOverLifetime {
        get angularVelocity() {
            return this._angularVelocity;
        }
        constructor(angularVelocity) {
            this._angularVelocity = angularVelocity;
        }
        cloneTo(destObject) {
            this._angularVelocity.cloneTo(destObject._angularVelocity);
            destObject.enable = this.enable;
        }
        clone() {
            var destAngularVelocity;
            switch (this._angularVelocity.type) {
                case 0:
                    if (this._angularVelocity.separateAxes)
                        destAngularVelocity = GradientAngularVelocity.createByConstantSeparate(this._angularVelocity.constantSeparate.clone());
                    else
                        destAngularVelocity = GradientAngularVelocity.createByConstant(this._angularVelocity.constant);
                    break;
                case 1:
                    if (this._angularVelocity.separateAxes)
                        destAngularVelocity = GradientAngularVelocity.createByGradientSeparate(this._angularVelocity.gradientX.clone(), this._angularVelocity.gradientY.clone(), this._angularVelocity.gradientZ.clone());
                    else
                        destAngularVelocity = GradientAngularVelocity.createByGradient(this._angularVelocity.gradient.clone());
                    break;
                case 2:
                    if (this._angularVelocity.separateAxes)
                        destAngularVelocity = GradientAngularVelocity.createByRandomTwoConstantSeparate(this._angularVelocity.constantMinSeparate.clone(), this._angularVelocity.constantMaxSeparate.clone());
                    else
                        destAngularVelocity = GradientAngularVelocity.createByRandomTwoConstant(this._angularVelocity.constantMin, this._angularVelocity.constantMax);
                    break;
                case 3:
                    if (this._angularVelocity.separateAxes)
                        destAngularVelocity = GradientAngularVelocity.createByRandomTwoGradientSeparate(this._angularVelocity.gradientXMin.clone(), this._angularVelocity.gradientXMax.clone(), this._angularVelocity.gradientYMin.clone(), this._angularVelocity.gradientYMax.clone(), this._angularVelocity.gradientZMin.clone(), this._angularVelocity.gradientZMax.clone(), this._angularVelocity.gradientWMin.clone(), this._angularVelocity.gradientWMax.clone());
                    else
                        destAngularVelocity = GradientAngularVelocity.createByRandomTwoGradient(this._angularVelocity.gradientMin.clone(), this._angularVelocity.gradientMax.clone());
                    break;
            }
            var destRotationOverLifetime = new RotationOverLifetime(destAngularVelocity);
            destRotationOverLifetime.enable = this.enable;
            return destRotationOverLifetime;
        }
    }

    exports.ParticleSystemShapeType = void 0;
    (function (ParticleSystemShapeType) {
        ParticleSystemShapeType[ParticleSystemShapeType["Box"] = 0] = "Box";
        ParticleSystemShapeType[ParticleSystemShapeType["Circle"] = 1] = "Circle";
        ParticleSystemShapeType[ParticleSystemShapeType["Cone"] = 2] = "Cone";
        ParticleSystemShapeType[ParticleSystemShapeType["Hemisphere"] = 3] = "Hemisphere";
        ParticleSystemShapeType[ParticleSystemShapeType["Sphere"] = 4] = "Sphere";
    })(exports.ParticleSystemShapeType || (exports.ParticleSystemShapeType = {}));
    class BaseShape {
        constructor() {
            this.enable = true;
            this.randomDirection = 0;
        }
        _getShapeBoundBox(boundBox) {
            throw new Error("BaseShape: must override it.");
        }
        _getSpeedBoundBox(boundBox) {
            throw new Error("BaseShape: must override it.");
        }
        generatePositionAndDirection(position, direction, rand = null, randomSeeds = null) {
            throw new Error("BaseShape: must override it.");
        }
        _calculateProceduralBounds(boundBox, emitterPosScale, minMaxBounds) {
            this._getShapeBoundBox(boundBox);
            var min = boundBox.min;
            var max = boundBox.max;
            Laya.Vector3.multiply(min, emitterPosScale, min);
            Laya.Vector3.multiply(max, emitterPosScale, max);
            var speedBounds = new Laya.BoundBox(new Laya.Vector3(), new Laya.Vector3());
            if (this.randomDirection) {
                speedBounds.min = new Laya.Vector3(-1, -1, -1);
                speedBounds.max = new Laya.Vector3(1, 1, 1);
            }
            else {
                this._getSpeedBoundBox(speedBounds);
            }
            var maxSpeedBound = new Laya.BoundBox(new Laya.Vector3(), new Laya.Vector3());
            var maxSpeedMin = maxSpeedBound.min;
            var maxSpeedMax = maxSpeedBound.max;
            Laya.Vector3.scale(speedBounds.min, minMaxBounds.y, maxSpeedMin);
            Laya.Vector3.scale(speedBounds.max, minMaxBounds.y, maxSpeedMax);
            Laya.Vector3.add(boundBox.min, maxSpeedMin, maxSpeedMin);
            Laya.Vector3.add(boundBox.max, maxSpeedMax, maxSpeedMax);
            Laya.Vector3.min(boundBox.min, maxSpeedMin, boundBox.min);
            Laya.Vector3.max(boundBox.max, maxSpeedMin, boundBox.max);
            var minSpeedBound = new Laya.BoundBox(new Laya.Vector3(), new Laya.Vector3());
            var minSpeedMin = minSpeedBound.min;
            var minSpeedMax = minSpeedBound.max;
            Laya.Vector3.scale(speedBounds.min, minMaxBounds.x, minSpeedMin);
            Laya.Vector3.scale(speedBounds.max, minMaxBounds.x, minSpeedMax);
            Laya.Vector3.min(minSpeedBound.min, minSpeedMax, maxSpeedMin);
            Laya.Vector3.max(minSpeedBound.min, minSpeedMax, maxSpeedMax);
            Laya.Vector3.min(boundBox.min, maxSpeedMin, boundBox.min);
            Laya.Vector3.max(boundBox.max, maxSpeedMin, boundBox.max);
        }
        cloneTo(destObject) {
            destObject.enable = this.enable;
        }
        clone() {
            var destShape = new BaseShape();
            this.cloneTo(destShape);
            return destShape;
        }
    }

    class ShapeUtils {
        static _randomPointUnitArcCircle(arc, out, rand = null) {
            var angle;
            if (rand)
                angle = rand.getFloat() * arc;
            else
                angle = Math.random() * arc;
            out.x = Math.cos(angle);
            out.y = Math.sin(angle);
        }
        static _randomPointInsideUnitArcCircle(arc, out, rand = null) {
            ShapeUtils._randomPointUnitArcCircle(arc, out, rand);
            var range;
            if (rand)
                range = Math.pow(rand.getFloat(), 1.0 / 2.0);
            else
                range = Math.pow(Math.random(), 1.0 / 2.0);
            out.x = out.x * range;
            out.y = out.y * range;
        }
        static _randomPointUnitCircle(out, rand = null) {
            var angle;
            if (rand)
                angle = rand.getFloat() * Math.PI * 2;
            else
                angle = Math.random() * Math.PI * 2;
            out.x = Math.cos(angle);
            out.y = Math.sin(angle);
        }
        static _randomPointInsideUnitCircle(out, rand = null) {
            ShapeUtils._randomPointUnitCircle(out, rand);
            var range;
            if (rand)
                range = Math.pow(rand.getFloat(), 1.0 / 2.0);
            else
                range = Math.pow(Math.random(), 1.0 / 2.0);
            out.x = out.x * range;
            out.y = out.y * range;
        }
        static _randomPointUnitSphere(out, rand = null) {
            var z;
            var a;
            if (rand) {
                z = out.z = rand.getFloat() * 2 - 1.0;
                a = rand.getFloat() * Math.PI * 2;
            }
            else {
                z = out.z = Math.random() * 2 - 1.0;
                a = Math.random() * Math.PI * 2;
            }
            var r = Math.sqrt(1.0 - z * z);
            out.x = r * Math.cos(a);
            out.y = r * Math.sin(a);
        }
        static _randomPointInsideUnitSphere(out, rand = null) {
            ShapeUtils._randomPointUnitSphere(out, rand);
            var range;
            if (rand)
                range = Math.pow(rand.getFloat(), 1.0 / 3.0);
            else
                range = Math.pow(Math.random(), 1.0 / 3.0);
            out.x = out.x * range;
            out.y = out.y * range;
            out.z = out.z * range;
        }
        static _randomPointInsideHalfUnitBox(out, rand = null) {
            if (rand) {
                out.x = (rand.getFloat() - 0.5);
                out.y = (rand.getFloat() - 0.5);
                out.z = (rand.getFloat() - 0.5);
            }
            else {
                out.x = (Math.random() - 0.5);
                out.y = (Math.random() - 0.5);
                out.z = (Math.random() - 0.5);
            }
        }
        constructor() {
        }
    }

    class BoxShape extends BaseShape {
        constructor() {
            super();
            this.shapeType = exports.ParticleSystemShapeType.Box;
            this.x = 1.0;
            this.y = 1.0;
            this.z = 1.0;
        }
        _getShapeBoundBox(boundBox) {
            var min = boundBox.min;
            min.x = -this.x * 0.5;
            min.y = -this.y * 0.5;
            min.z = -this.z * 0.5;
            var max = boundBox.max;
            max.x = this.x * 0.5;
            max.y = this.y * 0.5;
            max.z = this.z * 0.5;
        }
        _getSpeedBoundBox(boundBox) {
            var min = boundBox.min;
            min.x = 0.0;
            min.y = 0.0;
            min.z = 0.0;
            var max = boundBox.max;
            max.x = 0.0;
            max.y = 1.0;
            max.z = 0.0;
        }
        generatePositionAndDirection(position, direction, rand = null, randomSeeds = null) {
            if (rand) {
                rand.seed = randomSeeds[16];
                ShapeUtils._randomPointInsideHalfUnitBox(position, rand);
                randomSeeds[16] = rand.seed;
            }
            else {
                ShapeUtils._randomPointInsideHalfUnitBox(position);
            }
            position.x = this.x * position.x;
            position.y = this.y * position.y;
            position.z = this.z * position.z;
            if (this.randomDirection) {
                if (rand) {
                    rand.seed = randomSeeds[17];
                    ShapeUtils._randomPointUnitSphere(direction, rand);
                    randomSeeds[17] = rand.seed;
                }
                else {
                    ShapeUtils._randomPointUnitSphere(direction);
                }
            }
            else {
                direction.x = 0.0;
                direction.y = 0.0;
                direction.z = 1.0;
            }
        }
        cloneTo(destObject) {
            super.cloneTo(destObject);
            destObject.x = this.x;
            destObject.y = this.y;
            destObject.z = this.z;
            destObject.randomDirection = this.randomDirection;
        }
        clone() {
            var destShape = new BoxShape();
            this.cloneTo(destShape);
            return destShape;
        }
    }

    class CircleShape extends BaseShape {
        constructor() {
            super();
            this.shapeType = exports.ParticleSystemShapeType.Circle;
            this.radius = 1.0;
            this.arc = 360.0 / 180.0 * Math.PI;
            this.emitFromEdge = false;
        }
        get arcDEG() {
            return this.arc * 180 / Math.PI;
        }
        set arcDEG(deg) {
            this.arc = deg / 180 * Math.PI;
        }
        _getShapeBoundBox(boundBox) {
            var min = boundBox.min;
            min.x = min.z = -this.radius;
            min.y = 0;
            var max = boundBox.max;
            max.x = max.z = this.radius;
            max.y = 0;
        }
        _getSpeedBoundBox(boundBox) {
            var min = boundBox.min;
            min.x = min.y = -1;
            min.z = 0;
            var max = boundBox.max;
            max.x = max.y = 1;
            max.z = 0;
        }
        generatePositionAndDirection(position, direction, rand = null, randomSeeds = null) {
            var positionPoint = CircleShape._tempPositionPoint;
            if (rand) {
                rand.seed = randomSeeds[16];
                if (this.emitFromEdge)
                    ShapeUtils._randomPointUnitArcCircle(this.arc, CircleShape._tempPositionPoint, rand);
                else
                    ShapeUtils._randomPointInsideUnitArcCircle(this.arc, CircleShape._tempPositionPoint, rand);
                randomSeeds[16] = rand.seed;
            }
            else {
                if (this.emitFromEdge)
                    ShapeUtils._randomPointUnitArcCircle(this.arc, CircleShape._tempPositionPoint);
                else
                    ShapeUtils._randomPointInsideUnitArcCircle(this.arc, CircleShape._tempPositionPoint);
            }
            position.x = -positionPoint.x;
            position.y = positionPoint.y;
            position.z = 0;
            Laya.Vector3.scale(position, this.radius, position);
            if (this.randomDirection) {
                if (rand) {
                    rand.seed = randomSeeds[17];
                    ShapeUtils._randomPointUnitSphere(direction, rand);
                    randomSeeds[17] = rand.seed;
                }
                else {
                    ShapeUtils._randomPointUnitSphere(direction);
                }
            }
            else {
                position.cloneTo(direction);
            }
        }
        cloneTo(destObject) {
            super.cloneTo(destObject);
            destObject.radius = this.radius;
            destObject.arc = this.arc;
            destObject.emitFromEdge = this.emitFromEdge;
            destObject.randomDirection = this.randomDirection;
        }
        clone() {
            var destShape = new CircleShape();
            this.cloneTo(destShape);
            return destShape;
        }
    }
    CircleShape._tempPositionPoint = new Laya.Vector2();

    class ConeShape extends BaseShape {
        constructor() {
            super();
            this.shapeType = exports.ParticleSystemShapeType.Cone;
            this.angle = 25.0 / 180.0 * Math.PI;
            this.radius = 1.0;
            this.length = 5.0;
            this.emitType = 0;
        }
        get angleDEG() {
            return this.angle * 180 / Math.PI;
        }
        set angleDEG(deg) {
            this.angle = deg / 180 * Math.PI;
        }
        _getShapeBoundBox(boundBox) {
            const coneRadius2 = this.radius + this.length * Math.sin(this.angle);
            const coneLength = this.length * Math.cos(this.angle);
            var min = boundBox.min;
            min.x = min.y = -coneRadius2;
            min.z = 0;
            var max = boundBox.max;
            max.x = max.y = coneRadius2;
            max.z = coneLength;
        }
        _getSpeedBoundBox(boundBox) {
            const sinA = Math.sin(this.angle);
            var min = boundBox.min;
            min.x = min.y = -sinA;
            min.z = 0;
            var max = boundBox.max;
            max.x = max.y = sinA;
            max.z = 1;
        }
        generatePositionAndDirection(position, direction, rand = null, randomSeeds = null) {
            var positionPointE = ConeShape._tempPositionPoint;
            var positionX;
            var positionY;
            var directionPointE;
            var dirCosA = Math.cos(this.angle);
            var dirSinA = Math.sin(this.angle);
            switch (this.emitType) {
                case 0:
                    if (rand) {
                        rand.seed = randomSeeds[16];
                        ShapeUtils._randomPointInsideUnitCircle(ConeShape._tempPositionPoint, rand);
                        randomSeeds[16] = rand.seed;
                    }
                    else {
                        ShapeUtils._randomPointInsideUnitCircle(ConeShape._tempPositionPoint);
                    }
                    positionX = positionPointE.x;
                    positionY = positionPointE.y;
                    position.x = positionX * this.radius;
                    position.y = positionY * this.radius;
                    position.z = 0;
                    if (this.randomDirection) {
                        if (rand) {
                            rand.seed = randomSeeds[17];
                            ShapeUtils._randomPointInsideUnitCircle(ConeShape._tempDirectionPoint, rand);
                            randomSeeds[17] = rand.seed;
                        }
                        else {
                            ShapeUtils._randomPointInsideUnitCircle(ConeShape._tempDirectionPoint);
                        }
                        directionPointE = ConeShape._tempDirectionPoint;
                        direction.x = directionPointE.x * dirSinA;
                        direction.y = directionPointE.y * dirSinA;
                    }
                    else {
                        direction.x = positionX * dirSinA;
                        direction.y = positionY * dirSinA;
                    }
                    direction.z = dirCosA;
                    break;
                case 1:
                    if (rand) {
                        rand.seed = randomSeeds[16];
                        ShapeUtils._randomPointUnitCircle(ConeShape._tempPositionPoint, rand);
                        randomSeeds[16] = rand.seed;
                    }
                    else {
                        ShapeUtils._randomPointUnitCircle(ConeShape._tempPositionPoint);
                    }
                    positionX = positionPointE.x;
                    positionY = positionPointE.y;
                    position.x = positionX * this.radius;
                    position.y = positionY * this.radius;
                    position.z = 0;
                    if (this.randomDirection) {
                        if (rand) {
                            rand.seed = randomSeeds[17];
                            ShapeUtils._randomPointInsideUnitCircle(ConeShape._tempDirectionPoint, rand);
                            randomSeeds[17] = rand.seed;
                        }
                        else {
                            ShapeUtils._randomPointInsideUnitCircle(ConeShape._tempDirectionPoint);
                        }
                        directionPointE = ConeShape._tempDirectionPoint;
                        direction.x = directionPointE.x * dirSinA;
                        direction.y = directionPointE.y * dirSinA;
                    }
                    else {
                        direction.x = positionX * dirSinA;
                        direction.y = positionY * dirSinA;
                    }
                    direction.z = dirCosA;
                    break;
                case 2:
                    if (rand) {
                        rand.seed = randomSeeds[16];
                        ShapeUtils._randomPointInsideUnitCircle(ConeShape._tempPositionPoint, rand);
                    }
                    else {
                        ShapeUtils._randomPointInsideUnitCircle(ConeShape._tempPositionPoint);
                    }
                    positionX = positionPointE.x;
                    positionY = positionPointE.y;
                    position.x = positionX * this.radius;
                    position.y = positionY * this.radius;
                    position.z = 0;
                    direction.x = positionX * dirSinA;
                    direction.y = positionY * dirSinA;
                    direction.z = dirCosA;
                    Laya.Vector3.normalize(direction, direction);
                    if (rand) {
                        Laya.Vector3.scale(direction, this.length * rand.getFloat(), direction);
                        randomSeeds[16] = rand.seed;
                    }
                    else {
                        Laya.Vector3.scale(direction, this.length * Math.random(), direction);
                    }
                    Laya.Vector3.add(position, direction, position);
                    if (this.randomDirection) {
                        if (rand) {
                            rand.seed = randomSeeds[17];
                            ShapeUtils._randomPointUnitSphere(direction, rand);
                            randomSeeds[17] = rand.seed;
                        }
                        else {
                            ShapeUtils._randomPointUnitSphere(direction);
                        }
                    }
                    break;
                case 3:
                    if (rand) {
                        rand.seed = randomSeeds[16];
                        ShapeUtils._randomPointUnitCircle(ConeShape._tempPositionPoint, rand);
                    }
                    else {
                        ShapeUtils._randomPointUnitCircle(ConeShape._tempPositionPoint);
                    }
                    positionX = positionPointE.x;
                    positionY = positionPointE.y;
                    position.x = positionX * this.radius;
                    position.y = positionY * this.radius;
                    position.z = 0;
                    direction.x = positionX * dirSinA;
                    direction.y = positionY * dirSinA;
                    direction.z = dirCosA;
                    Laya.Vector3.normalize(direction, direction);
                    if (rand) {
                        Laya.Vector3.scale(direction, this.length * rand.getFloat(), direction);
                        randomSeeds[16] = rand.seed;
                    }
                    else {
                        Laya.Vector3.scale(direction, this.length * Math.random(), direction);
                    }
                    Laya.Vector3.add(position, direction, position);
                    if (this.randomDirection) {
                        if (rand) {
                            rand.seed = randomSeeds[17];
                            ShapeUtils._randomPointUnitSphere(direction, rand);
                            randomSeeds[17] = rand.seed;
                        }
                        else {
                            ShapeUtils._randomPointUnitSphere(direction);
                        }
                    }
                    break;
                default:
                    throw new Error("ConeShape:emitType is invalid.");
            }
        }
        cloneTo(destObject) {
            super.cloneTo(destObject);
            destObject.angle = this.angle;
            destObject.radius = this.radius;
            destObject.length = this.length;
            destObject.emitType = this.emitType;
            destObject.randomDirection = this.randomDirection;
        }
        clone() {
            var destShape = new ConeShape();
            this.cloneTo(destShape);
            return destShape;
        }
    }
    ConeShape._tempPositionPoint = new Laya.Vector2();
    ConeShape._tempDirectionPoint = new Laya.Vector2();

    class HemisphereShape extends BaseShape {
        constructor() {
            super();
            this.shapeType = exports.ParticleSystemShapeType.Hemisphere;
            this.radius = 1.0;
            this.emitFromShell = false;
        }
        _getShapeBoundBox(boundBox) {
            var min = boundBox.min;
            min.x = min.y = min.z = -this.radius;
            var max = boundBox.max;
            max.x = max.y = this.radius;
            max.z = 0;
        }
        _getSpeedBoundBox(boundBox) {
            var min = boundBox.min;
            min.x = min.y = -1;
            min.z = 0;
            var max = boundBox.max;
            max.x = max.y = max.z = 1;
        }
        generatePositionAndDirection(position, direction, rand = null, randomSeeds = null) {
            if (rand) {
                rand.seed = randomSeeds[16];
                if (this.emitFromShell)
                    ShapeUtils._randomPointUnitSphere(position, rand);
                else
                    ShapeUtils._randomPointInsideUnitSphere(position, rand);
                randomSeeds[16] = rand.seed;
            }
            else {
                if (this.emitFromShell)
                    ShapeUtils._randomPointUnitSphere(position);
                else
                    ShapeUtils._randomPointInsideUnitSphere(position);
            }
            Laya.Vector3.scale(position, this.radius, position);
            var z = position.z;
            (z < 0.0) && (position.z = z * -1.0);
            if (this.randomDirection) {
                if (rand) {
                    rand.seed = randomSeeds[17];
                    ShapeUtils._randomPointUnitSphere(direction, rand);
                    randomSeeds[17] = rand.seed;
                }
                else {
                    ShapeUtils._randomPointUnitSphere(direction);
                }
            }
            else {
                position.cloneTo(direction);
            }
        }
        cloneTo(destObject) {
            super.cloneTo(destObject);
            destObject.radius = this.radius;
            destObject.emitFromShell = this.emitFromShell;
            destObject.randomDirection = this.randomDirection;
        }
        clone() {
            var destShape = new HemisphereShape();
            this.cloneTo(destShape);
            return destShape;
        }
    }

    class SphereShape extends BaseShape {
        constructor() {
            super();
            this.shapeType = exports.ParticleSystemShapeType.Sphere;
            this.radius = 1.0;
            this.emitFromShell = false;
        }
        _getShapeBoundBox(boundBox) {
            var min = boundBox.min;
            min.x = min.y = min.z = -this.radius;
            var max = boundBox.max;
            max.x = max.y = max.z = this.radius;
        }
        _getSpeedBoundBox(boundBox) {
            var min = boundBox.min;
            min.x = min.y = min.z = -1;
            var max = boundBox.max;
            max.x = max.y = max.z = 1;
        }
        generatePositionAndDirection(position, direction, rand = null, randomSeeds = null) {
            if (rand) {
                rand.seed = randomSeeds[16];
                if (this.emitFromShell)
                    ShapeUtils._randomPointUnitSphere(position, rand);
                else
                    ShapeUtils._randomPointInsideUnitSphere(position, rand);
                randomSeeds[16] = rand.seed;
            }
            else {
                if (this.emitFromShell)
                    ShapeUtils._randomPointUnitSphere(position);
                else
                    ShapeUtils._randomPointInsideUnitSphere(position);
            }
            Laya.Vector3.scale(position, this.radius, position);
            if (this.randomDirection) {
                if (rand) {
                    rand.seed = randomSeeds[17];
                    ShapeUtils._randomPointUnitSphere(direction, rand);
                    randomSeeds[17] = rand.seed;
                }
                else {
                    ShapeUtils._randomPointUnitSphere(direction);
                }
            }
            else {
                position.cloneTo(direction);
            }
        }
        cloneTo(destObject) {
            super.cloneTo(destObject);
            destObject.radius = this.radius;
            destObject.emitFromShell = this.emitFromShell;
            destObject.randomDirection = this.randomDirection;
        }
        clone() {
            var destShape = new SphereShape();
            this.cloneTo(destShape);
            return destShape;
        }
    }

    class SizeOverLifetime {
        get size() {
            return this._size;
        }
        constructor(size) {
            this._size = size;
        }
        cloneTo(destObject) {
            this._size.cloneTo(destObject._size);
            destObject.enable = this.enable;
        }
        clone() {
            var destSize;
            switch (this._size.type) {
                case 0:
                    if (this._size.separateAxes)
                        destSize = GradientSize.createByGradientSeparate(this._size.gradientX.clone(), this._size.gradientY.clone(), this._size.gradientZ.clone());
                    else
                        destSize = GradientSize.createByGradient(this._size.gradient.clone());
                    break;
                case 1:
                    if (this._size.separateAxes)
                        destSize = GradientSize.createByRandomTwoConstantSeparate(this._size.constantMinSeparate.clone(), this._size.constantMaxSeparate.clone());
                    else
                        destSize = GradientSize.createByRandomTwoConstant(this._size.constantMin, this._size.constantMax);
                    break;
                case 2:
                    if (this._size.separateAxes)
                        destSize = GradientSize.createByRandomTwoGradientSeparate(this._size.gradientXMin.clone(), this._size.gradientYMin.clone(), this._size.gradientZMin.clone(), this._size.gradientXMax.clone(), this._size.gradientYMax.clone(), this._size.gradientZMax.clone());
                    else
                        destSize = GradientSize.createByRandomTwoGradient(this._size.gradientMin.clone(), this._size.gradientMax.clone());
                    break;
            }
            var destSizeOverLifetime = new SizeOverLifetime(destSize);
            destSizeOverLifetime.enable = this.enable;
            return destSizeOverLifetime;
        }
    }

    class StartFrame {
        static createByConstant(constant = 0) {
            var rotationOverLifetime = new StartFrame();
            rotationOverLifetime._type = 0;
            rotationOverLifetime._constant = constant;
            return rotationOverLifetime;
        }
        static createByRandomTwoConstant(constantMin = 0, constantMax = 0) {
            var rotationOverLifetime = new StartFrame();
            rotationOverLifetime._type = 1;
            rotationOverLifetime._constantMin = constantMin;
            rotationOverLifetime._constantMax = constantMax;
            return rotationOverLifetime;
        }
        get type() {
            return this._type;
        }
        get constant() {
            return this._constant;
        }
        get constantMin() {
            return this._constantMin;
        }
        get constantMax() {
            return this._constantMax;
        }
        constructor() {
            this._type = 0;
            this._constant = 0;
            this._constantMin = 0;
            this._constantMax = 0;
        }
        cloneTo(destObject) {
            destObject._type = this._type;
            destObject._constant = this._constant;
            destObject._constantMin = this._constantMin;
            destObject._constantMax = this._constantMax;
        }
        clone() {
            var destStartFrame = new StartFrame();
            this.cloneTo(destStartFrame);
            return destStartFrame;
        }
    }

    class TextureSheetAnimation {
        get frame() {
            return this._frame;
        }
        get startFrame() {
            return this._startFrame;
        }
        constructor(frame, startFrame) {
            this.type = 0;
            this.randomRow = false;
            this.rowIndex = 0;
            this.cycles = 0;
            this.enableUVChannels = 0;
            this.enable = false;
            this.tiles = new Laya.Vector2(1, 1);
            this.type = 0;
            this.randomRow = true;
            this.rowIndex = 0;
            this.cycles = 1;
            this.enableUVChannels = 1;
            this._frame = frame;
            this._startFrame = startFrame;
        }
        cloneTo(destObject) {
            this.tiles.cloneTo(destObject.tiles);
            destObject.type = this.type;
            destObject.randomRow = this.randomRow;
            destObject.rowIndex = this.rowIndex;
            destObject.cycles = this.cycles;
            destObject.enableUVChannels = this.enableUVChannels;
            destObject.enable = this.enable;
            this._frame.cloneTo(destObject._frame);
            this._startFrame.cloneTo(destObject._startFrame);
        }
        clone() {
            var destFrame;
            switch (this._frame.type) {
                case 0:
                    destFrame = FrameOverTime.createByConstant(this._frame.constant);
                    break;
                case 1:
                    destFrame = FrameOverTime.createByOverTime(this._frame.frameOverTimeData.clone());
                    break;
                case 2:
                    destFrame = FrameOverTime.createByRandomTwoConstant(this._frame.constantMin, this._frame.constantMax);
                    break;
                case 3:
                    destFrame = FrameOverTime.createByRandomTwoOverTime(this._frame.frameOverTimeDataMin.clone(), this._frame.frameOverTimeDataMax.clone());
                    break;
            }
            var destStartFrame;
            switch (this._startFrame.type) {
                case 0:
                    destStartFrame = StartFrame.createByConstant(this._startFrame.constant);
                    break;
                case 1:
                    destStartFrame = StartFrame.createByRandomTwoConstant(this._startFrame.constantMin, this._startFrame.constantMax);
                    break;
            }
            var destTextureSheetAnimation = new TextureSheetAnimation(destFrame, destStartFrame);
            this.cloneTo(destTextureSheetAnimation);
            return destTextureSheetAnimation;
        }
    }

    class VelocityOverLifetime {
        get velocity() {
            return this._velocity;
        }
        constructor(velocity) {
            this.enable = false;
            this.space = 0;
            this._velocity = velocity;
        }
        cloneTo(destObject) {
            this._velocity.cloneTo(destObject._velocity);
            destObject.enable = this.enable;
            destObject.space = this.space;
        }
        clone() {
            var destVelocity;
            switch (this._velocity.type) {
                case 0:
                    destVelocity = GradientVelocity.createByConstant(this._velocity.constant.clone());
                    break;
                case 1:
                    destVelocity = GradientVelocity.createByGradient(this._velocity.gradientX.clone(), this._velocity.gradientY.clone(), this._velocity.gradientZ.clone());
                    break;
                case 2:
                    destVelocity = GradientVelocity.createByRandomTwoConstant(this._velocity.constantMin.clone(), this._velocity.constantMax.clone());
                    break;
                case 3:
                    destVelocity = GradientVelocity.createByRandomTwoGradient(this._velocity.gradientXMin.clone(), this._velocity.gradientXMax.clone(), this._velocity.gradientYMin.clone(), this._velocity.gradientYMax.clone(), this._velocity.gradientZMin.clone(), this._velocity.gradientZMax.clone());
                    break;
            }
            var destVelocityOverLifetime = new VelocityOverLifetime(destVelocity);
            destVelocityOverLifetime.enable = this.enable;
            destVelocityOverLifetime.space = this.space;
            return destVelocityOverLifetime;
        }
    }

    var ShurikenVS = "#define SHADER_NAME ParticleVS\n#include \"Camera.glsl\";\n#include \"particleShuriKenSpriteVS.glsl\";\n#include \"Math.glsl\";\n#include \"MathGradient.glsl\";\n#include \"Color.glsl\";\n#include \"Scene.glsl\"\n#include \"SceneFogInput.glsl\"\n#ifdef RENDERMODE_MESH\nvarying vec4 v_MeshColor;\n#endif\nvarying vec4 v_Color;varying vec2 v_TextureCoordinate;vec2 TransformUV(vec2 texcoord,vec4 tilingOffset){vec2 transTexcoord=vec2(texcoord.x,texcoord.y-1.0)*tilingOffset.xy+vec2(tilingOffset.z,-tilingOffset.w);transTexcoord.y+=1.0;return transTexcoord;}\n#if defined(VELOCITYOVERLIFETIMECONSTANT) || defined(VELOCITYOVERLIFETIMECURVE) || defined(VELOCITYOVERLIFETIMERANDOMCONSTANT) || defined(VELOCITYOVERLIFETIMERANDOMCURVE)\nvec3 computeParticleLifeVelocity(in float normalizedAge){vec3 outLifeVelocity;\n#ifdef VELOCITYOVERLIFETIMECONSTANT\noutLifeVelocity=u_VOLVelocityConst;\n#endif\n#ifdef VELOCITYOVERLIFETIMECURVE\noutLifeVelocity=vec3(getCurValueFromGradientFloat(u_VOLVelocityGradientX,normalizedAge),getCurValueFromGradientFloat(u_VOLVelocityGradientY,normalizedAge),getCurValueFromGradientFloat(u_VOLVelocityGradientZ,normalizedAge));\n#endif\n#ifdef VELOCITYOVERLIFETIMERANDOMCONSTANT\noutLifeVelocity=mix(u_VOLVelocityConst,u_VOLVelocityConstMax,vec3(a_Random1.y,a_Random1.z,a_Random1.w));\n#endif\n#ifdef VELOCITYOVERLIFETIMERANDOMCURVE\noutLifeVelocity=vec3(mix(getCurValueFromGradientFloat(u_VOLVelocityGradientX,normalizedAge),getCurValueFromGradientFloat(u_VOLVelocityGradientMaxX,normalizedAge),a_Random1.y),mix(getCurValueFromGradientFloat(u_VOLVelocityGradientY,normalizedAge),getCurValueFromGradientFloat(u_VOLVelocityGradientMaxY,normalizedAge),a_Random1.z),mix(getCurValueFromGradientFloat(u_VOLVelocityGradientZ,normalizedAge),getCurValueFromGradientFloat(u_VOLVelocityGradientMaxZ,normalizedAge),a_Random1.w));\n#endif\nreturn outLifeVelocity;}\n#endif\nvec3 getStartPosition(vec3 startVelocity,float age,vec3 dragData){vec3 startPosition;float lasttime=min(startVelocity.x/dragData.x,age);startPosition=lasttime*(startVelocity-0.5*dragData*lasttime);return startPosition;}vec3 computeParticlePosition(in vec3 startVelocity,in vec3 lifeVelocity,in float age,in float normalizedAge,vec3 gravityVelocity,vec4 worldRotation,vec3 dragData){vec3 startPosition=getStartPosition(startVelocity,age,dragData);vec3 lifePosition;\n#if defined(VELOCITYOVERLIFETIMECONSTANT) || defined(VELOCITYOVERLIFETIMECURVE) || defined(VELOCITYOVERLIFETIMERANDOMCONSTANT) || defined(VELOCITYOVERLIFETIMERANDOMCURVE)\n#ifdef VELOCITYOVERLIFETIMECONSTANT\nlifePosition=lifeVelocity*age;\n#endif\n#ifdef VELOCITYOVERLIFETIMECURVE\nlifePosition=vec3(getTotalValueFromGradientFloat(u_VOLVelocityGradientX,normalizedAge),getTotalValueFromGradientFloat(u_VOLVelocityGradientY,normalizedAge),getTotalValueFromGradientFloat(u_VOLVelocityGradientZ,normalizedAge));\n#endif\n#ifdef VELOCITYOVERLIFETIMERANDOMCONSTANT\nlifePosition=lifeVelocity*age;\n#endif\n#ifdef VELOCITYOVERLIFETIMERANDOMCURVE\nlifePosition=vec3(mix(getTotalValueFromGradientFloat(u_VOLVelocityGradientX,normalizedAge),getTotalValueFromGradientFloat(u_VOLVelocityGradientMaxX,normalizedAge),a_Random1.y),mix(getTotalValueFromGradientFloat(u_VOLVelocityGradientY,normalizedAge),getTotalValueFromGradientFloat(u_VOLVelocityGradientMaxY,normalizedAge),a_Random1.z),mix(getTotalValueFromGradientFloat(u_VOLVelocityGradientZ,normalizedAge),getTotalValueFromGradientFloat(u_VOLVelocityGradientMaxZ,normalizedAge),a_Random1.w));\n#endif\nvec3 finalPosition;if(u_VOLSpaceType==0){if(u_ScalingMode!=2)finalPosition=rotationByQuaternions(u_PositionScale*(a_ShapePositionStartLifeTime.xyz+startPosition+lifePosition),worldRotation);else finalPosition=rotationByQuaternions(u_PositionScale*a_ShapePositionStartLifeTime.xyz+startPosition+lifePosition,worldRotation);}else{if(u_ScalingMode!=2)finalPosition=rotationByQuaternions(u_PositionScale*(a_ShapePositionStartLifeTime.xyz+startPosition),worldRotation)+lifePosition;else finalPosition=rotationByQuaternions(u_PositionScale*a_ShapePositionStartLifeTime.xyz+startPosition,worldRotation)+lifePosition;}\n#else\nvec3 finalPosition;if(u_ScalingMode!=2)finalPosition=rotationByQuaternions(u_PositionScale*(a_ShapePositionStartLifeTime.xyz+startPosition),worldRotation);else finalPosition=rotationByQuaternions(u_PositionScale*a_ShapePositionStartLifeTime.xyz+startPosition,worldRotation);\n#endif\nif(u_SimulationSpace==0)finalPosition=finalPosition+a_SimulationWorldPostion;else if(u_SimulationSpace==1)finalPosition=finalPosition+u_WorldPosition;finalPosition+=0.5*gravityVelocity*age;return finalPosition;}vec4 computeParticleColor(in vec4 color,in float normalizedAge){\n#ifdef COLOROVERLIFETIME\ncolor*=getColorFromGradient(u_ColorOverLifeGradientAlphas,u_ColorOverLifeGradientColors,normalizedAge,u_ColorOverLifeGradientRanges);\n#endif\n#ifdef RANDOMCOLOROVERLIFETIME\ncolor*=mix(getColorFromGradient(u_ColorOverLifeGradientAlphas,u_ColorOverLifeGradientColors,normalizedAge,u_ColorOverLifeGradientRanges),getColorFromGradient(u_MaxColorOverLifeGradientAlphas,u_MaxColorOverLifeGradientColors,normalizedAge,u_MaxColorOverLifeGradientRanges),a_Random0.y);\n#endif\nreturn color;}vec2 computeParticleSizeBillbard(in vec2 size,in float normalizedAge){\n#ifdef SIZEOVERLIFETIMECURVE\nsize*=getCurValueFromGradientFloat(u_SOLSizeGradient,normalizedAge);\n#endif\n#ifdef SIZEOVERLIFETIMERANDOMCURVES\nsize*=mix(getCurValueFromGradientFloat(u_SOLSizeGradient,normalizedAge),getCurValueFromGradientFloat(u_SOLSizeGradientMax,normalizedAge),a_Random0.z);\n#endif\n#ifdef SIZEOVERLIFETIMECURVESEPERATE\nsize*=vec2(getCurValueFromGradientFloat(u_SOLSizeGradientX,normalizedAge),getCurValueFromGradientFloat(u_SOLSizeGradientY,normalizedAge));\n#endif\n#ifdef SIZEOVERLIFETIMERANDOMCURVESSEPERATE\nsize*=vec2(mix(getCurValueFromGradientFloat(u_SOLSizeGradientX,normalizedAge),getCurValueFromGradientFloat(u_SOLSizeGradientMaxX,normalizedAge),a_Random0.z),mix(getCurValueFromGradientFloat(u_SOLSizeGradientY,normalizedAge),getCurValueFromGradientFloat(u_SOLSizeGradientMaxY,normalizedAge),a_Random0.z));\n#endif\nreturn size;}\n#ifdef RENDERMODE_MESH\nvec3 computeParticleSizeMesh(in vec3 size,in float normalizedAge){\n#ifdef SIZEOVERLIFETIMECURVE\nsize*=getCurValueFromGradientFloat(u_SOLSizeGradient,normalizedAge);\n#endif\n#ifdef SIZEOVERLIFETIMERANDOMCURVES\nsize*=mix(getCurValueFromGradientFloat(u_SOLSizeGradient,normalizedAge),getCurValueFromGradientFloat(u_SOLSizeGradientMax,normalizedAge),a_Random0.z);\n#endif\n#ifdef SIZEOVERLIFETIMECURVESEPERATE\nsize*=vec3(getCurValueFromGradientFloat(u_SOLSizeGradientX,normalizedAge),getCurValueFromGradientFloat(u_SOLSizeGradientY,normalizedAge),getCurValueFromGradientFloat(u_SOLSizeGradientZ,normalizedAge));\n#endif\n#ifdef SIZEOVERLIFETIMERANDOMCURVESSEPERATE\nsize*=vec3(mix(getCurValueFromGradientFloat(u_SOLSizeGradientX,normalizedAge),getCurValueFromGradientFloat(u_SOLSizeGradientMaxX,normalizedAge),a_Random0.z),mix(getCurValueFromGradientFloat(u_SOLSizeGradientY,normalizedAge),getCurValueFromGradientFloat(u_SOLSizeGradientMaxY,normalizedAge),a_Random0.z),mix(getCurValueFromGradientFloat(u_SOLSizeGradientZ,normalizedAge),getCurValueFromGradientFloat(u_SOLSizeGradientMaxZ,normalizedAge),a_Random0.z));\n#endif\nreturn size;}\n#endif\nfloat computeParticleRotationFloat(in float rotation,in float age,in float normalizedAge){\n#ifdef ROTATIONOVERLIFETIME\n#ifdef ROTATIONOVERLIFETIMECONSTANT\nfloat ageRot=u_ROLAngularVelocityConst*age;rotation+=ageRot;\n#endif\n#ifdef ROTATIONOVERLIFETIMECURVE\nrotation+=getTotalValueFromGradientFloat(u_ROLAngularVelocityGradient,normalizedAge);\n#endif\n#ifdef ROTATIONOVERLIFETIMERANDOMCONSTANTS\nfloat ageRot=mix(u_ROLAngularVelocityConst,u_ROLAngularVelocityConstMax,a_Random0.w)*age;rotation+=ageRot;\n#endif\n#ifdef ROTATIONOVERLIFETIMERANDOMCURVES\nrotation+=mix(getTotalValueFromGradientFloat(u_ROLAngularVelocityGradient,normalizedAge),getTotalValueFromGradientFloat(u_ROLAngularVelocityGradientMax,normalizedAge),a_Random0.w);\n#endif\n#endif\n#ifdef ROTATIONOVERLIFETIMESEPERATE\n#ifdef ROTATIONOVERLIFETIMECONSTANT\nfloat ageRot=u_ROLAngularVelocityConstSeprarate.z*age;rotation+=ageRot;\n#endif\n#ifdef ROTATIONOVERLIFETIMECURVE\nrotation+=getTotalValueFromGradientFloat(u_ROLAngularVelocityGradientZ,normalizedAge);\n#endif\n#ifdef ROTATIONOVERLIFETIMERANDOMCONSTANTS\nfloat ageRot=mix(u_ROLAngularVelocityConstSeprarate.z,u_ROLAngularVelocityConstMaxSeprarate.z,a_Random0.w)*age;rotation+=ageRot;\n#endif\n#ifdef ROTATIONOVERLIFETIMERANDOMCURVES\nrotation+=mix(getTotalValueFromGradientFloat(u_ROLAngularVelocityGradientZ,normalizedAge),getTotalValueFromGradientFloat(u_ROLAngularVelocityGradientMaxZ,normalizedAge),a_Random0.w);\n#endif\n#endif\nreturn rotation;}\n#if defined(RENDERMODE_MESH) && (defined(ROTATIONOVERLIFETIME) || defined(ROTATIONOVERLIFETIMESEPERATE))\nvec3 computeParticleRotationVec3(in vec3 rotation,in float age,in float normalizedAge){\n#ifdef ROTATIONOVERLIFETIME\n#ifdef ROTATIONOVERLIFETIMECONSTANT\nfloat ageRot=u_ROLAngularVelocityConst*age;rotation+=ageRot;\n#endif\n#ifdef ROTATIONOVERLIFETIMECURVE\nrotation+=getTotalValueFromGradientFloat(u_ROLAngularVelocityGradient,normalizedAge);\n#endif\n#ifdef ROTATIONOVERLIFETIMERANDOMCONSTANTS\nfloat ageRot=mix(u_ROLAngularVelocityConst,u_ROLAngularVelocityConstMax,a_Random0.w)*age;rotation+=ageRot;\n#endif\n#ifdef ROTATIONOVERLIFETIMERANDOMCURVES\nrotation+=mix(getTotalValueFromGradientFloat(u_ROLAngularVelocityGradient,normalizedAge),getTotalValueFromGradientFloat(u_ROLAngularVelocityGradientMax,normalizedAge),a_Random0.w);\n#endif\n#endif\n#ifdef ROTATIONOVERLIFETIMESEPERATE\n#ifdef ROTATIONOVERLIFETIMECONSTANT\nvec3 ageRot=u_ROLAngularVelocityConstSeprarate*age;rotation+=ageRot;\n#endif\n#ifdef ROTATIONOVERLIFETIMECURVE\nrotation+=vec3(getTotalValueFromGradientFloat(u_ROLAngularVelocityGradientX,normalizedAge),getTotalValueFromGradientFloat(u_ROLAngularVelocityGradientY,normalizedAge),getTotalValueFromGradientFloat(u_ROLAngularVelocityGradientZ,normalizedAge));\n#endif\n#ifdef ROTATIONOVERLIFETIMERANDOMCONSTANTS\nvec3 ageRot=mix(u_ROLAngularVelocityConstSeprarate,u_ROLAngularVelocityConstMaxSeprarate,a_Random0.w)*age;rotation+=ageRot;\n#endif\n#ifdef ROTATIONOVERLIFETIMERANDOMCURVES\nrotation+=vec3(mix(getTotalValueFromGradientFloat(u_ROLAngularVelocityGradientX,normalizedAge),getTotalValueFromGradientFloat(u_ROLAngularVelocityGradientMaxX,normalizedAge),a_Random0.w),mix(getTotalValueFromGradientFloat(u_ROLAngularVelocityGradientY,normalizedAge),getTotalValueFromGradientFloat(u_ROLAngularVelocityGradientMaxY,normalizedAge),a_Random0.w),mix(getTotalValueFromGradientFloat(u_ROLAngularVelocityGradientZ,normalizedAge),getTotalValueFromGradientFloat(u_ROLAngularVelocityGradientMaxZ,normalizedAge),a_Random0.w));\n#endif\n#endif\nreturn rotation;}\n#endif\nvec2 computeParticleUV(in vec2 uv,in float normalizedAge){\n#ifdef TEXTURESHEETANIMATIONCURVE\nfloat cycleNormalizedAge=normalizedAge*u_TSACycles;float frame=getFrameFromGradient(u_TSAGradientUVs,cycleNormalizedAge-floor(cycleNormalizedAge));float totalULength=frame*u_TSASubUVLength.x;float floorTotalULength=floor(totalULength);uv.x+=totalULength-floorTotalULength;uv.y+=floorTotalULength*u_TSASubUVLength.y;\n#endif\n#ifdef TEXTURESHEETANIMATIONRANDOMCURVE\nfloat cycleNormalizedAge=normalizedAge*u_TSACycles;float uvNormalizedAge=cycleNormalizedAge-floor(cycleNormalizedAge);float frame=floor(mix(getFrameFromGradient(u_TSAGradientUVs,uvNormalizedAge),getFrameFromGradient(u_TSAMaxGradientUVs,uvNormalizedAge),a_Random1.x));float totalULength=frame*u_TSASubUVLength.x;float floorTotalULength=floor(totalULength);uv.x+=totalULength-floorTotalULength;uv.y+=floorTotalULength*u_TSASubUVLength.y;\n#endif\nreturn uv;}void main(){float age=u_CurrentTime-a_DirectionTime.w;float normalizedAge=age/a_ShapePositionStartLifeTime.w;vec3 lifeVelocity;if(normalizedAge<1.0){vec3 startVelocity=a_DirectionTime.xyz*a_StartSpeed;\n#if defined(VELOCITYOVERLIFETIMECONSTANT) || defined(VELOCITYOVERLIFETIMECURVE) || defined(VELOCITYOVERLIFETIMERANDOMCONSTANT) || defined(VELOCITYOVERLIFETIMERANDOMCURVE)\nlifeVelocity=computeParticleLifeVelocity(normalizedAge);\n#endif\nvec3 gravityVelocity=u_Gravity*age;vec4 worldRotation;if(u_SimulationSpace==0)worldRotation=a_SimulationWorldRotation;else worldRotation=u_WorldRotation;vec3 dragData=a_DirectionTime.xyz*mix(u_DragConstanct.x,u_DragConstanct.y,a_Random0.x);vec3 center=computeParticlePosition(startVelocity,lifeVelocity,age,normalizedAge,gravityVelocity,worldRotation,dragData);\n#ifdef SPHERHBILLBOARD\nvec2 corner=a_CornerTextureCoordinate.xy;vec3 cameraUpVector=normalize(u_CameraUp);vec3 sideVector=normalize(cross(u_CameraDirection,cameraUpVector));vec3 upVector=normalize(cross(sideVector,u_CameraDirection));vec2 bbSize=computeParticleSizeBillbard(a_StartSize.xy,normalizedAge);corner*=bbSize;vec2 pivot2D=u_Pivot.xy*bbSize;corner+=pivot2D*vec2(-1.0,1.0);\n#if defined(ROTATIONOVERLIFETIME) || defined(ROTATIONOVERLIFETIMESEPERATE)\nif(u_ThreeDStartRotation!=0){vec3 rotation=vec3(a_StartRotation0.xy,computeParticleRotationFloat(a_StartRotation0.z,age,normalizedAge));center+=u_SizeScale.xzy*rotationByEuler(corner.x*sideVector+corner.y*upVector,rotation);}else{float rot=computeParticleRotationFloat(a_StartRotation0.x,age,normalizedAge);float c=cos(rot);float s=sin(rot);mat2 rotation=mat2(c,-s,s,c);corner=rotation*corner;center+=u_SizeScale.xzy*(corner.x*sideVector+corner.y*upVector);}\n#else\nif(u_ThreeDStartRotation!=0){center+=u_SizeScale.xzy*rotationByEuler(corner.x*sideVector+corner.y*upVector,a_StartRotation0);}else{float c=cos(a_StartRotation0.x);float s=sin(a_StartRotation0.x);mat2 rotation=mat2(c,-s,s,c);corner=rotation*corner;center+=u_SizeScale.xzy*(corner.x*sideVector+corner.y*upVector);}\n#endif\n#endif\n#ifdef STRETCHEDBILLBOARD\nvec2 corner=a_CornerTextureCoordinate.xy;vec3 velocity;\n#if defined(VELOCITYOVERLIFETIMECONSTANT) || defined(VELOCITYOVERLIFETIMECURVE) || defined(VELOCITYOVERLIFETIMERANDOMCONSTANT) || defined(VELOCITYOVERLIFETIMERANDOMCURVE)\nif(u_VOLSpaceType==0)velocity=rotationByQuaternions(u_SizeScale*(startVelocity+lifeVelocity),worldRotation)+gravityVelocity;else velocity=rotationByQuaternions(u_SizeScale*startVelocity,worldRotation)+lifeVelocity+gravityVelocity;\n#else\nvelocity=rotationByQuaternions(u_SizeScale*startVelocity,worldRotation)+gravityVelocity;\n#endif\nvec3 cameraUpVector=normalize(velocity);vec3 direction=normalize(center-u_CameraPos);vec3 sideVector=normalize(cross(direction,normalize(velocity)));sideVector=u_SizeScale.xzy*sideVector;cameraUpVector=length(vec3(u_SizeScale.x,0.0,0.0))*cameraUpVector;vec2 size=computeParticleSizeBillbard(a_StartSize.xy,normalizedAge);const mat2 rotaionZHalfPI=mat2(0.0,-1.0,1.0,0.0);corner=rotaionZHalfPI*corner;corner.y=corner.y-abs(corner.y);float speed=length(velocity);center+=sign(u_SizeScale.x)*(sign(u_StretchedBillboardLengthScale)*size.x*(corner.x-u_Pivot.x)*sideVector+(speed*u_StretchedBillboardSpeedScale+size.y*u_StretchedBillboardLengthScale)*(corner.y+u_Pivot.y)*cameraUpVector);\n#endif\n#ifdef HORIZONTALBILLBOARD\nvec2 corner=a_CornerTextureCoordinate.xy;const vec3 cameraUpVector=vec3(0.0,0.0,1.0);const vec3 sideVector=vec3(-1.0,0.0,0.0);vec2 hBbSize=computeParticleSizeBillbard(a_StartSize.xy,normalizedAge);corner+=u_Pivot.xy*vec2(-1.0,1.0);float rot=computeParticleRotationFloat(a_StartRotation0.x,age,normalizedAge);float c=cos(rot);float s=sin(rot);mat2 rotation=mat2(c,-s,s,c);corner=rotation*corner*cos(0.78539816339744830961566084581988);corner*=hBbSize;center+=u_SizeScale.xzy*(corner.x*sideVector+corner.y*cameraUpVector);\n#endif\n#ifdef VERTICALBILLBOARD\nvec2 corner=a_CornerTextureCoordinate.xy;const vec3 cameraUpVector=vec3(0.0,1.0,0.0);vec3 sideVector=normalize(cross(u_CameraDirection,cameraUpVector));vec2 vBbSize=computeParticleSizeBillbard(a_StartSize.xy,normalizedAge);corner+=u_Pivot.xy*vec2(-1.0,1.0);float rot=computeParticleRotationFloat(a_StartRotation0.x,age,normalizedAge);float c=cos(rot);float s=sin(rot);mat2 rotation=mat2(c,-s,s,c);corner=rotation*corner*cos(0.78539816339744830961566084581988);corner*=vBbSize;center+=u_SizeScale.xzy*(corner.x*sideVector+corner.y*cameraUpVector);\n#endif\n#ifdef RENDERMODE_MESH\nvec3 size=computeParticleSizeMesh(a_StartSize,normalizedAge);vec3 pivot=u_Pivot*size;vec3 scaledPivot=u_SizeScale*pivot;\n#if defined(ROTATIONOVERLIFETIME) || defined(ROTATIONOVERLIFETIMESEPERATE)\nif(u_ThreeDStartRotation!=0){vec3 rotation=vec3(a_StartRotation0.xy,computeParticleRotationFloat(a_StartRotation0.z,age,normalizedAge));center+=rotationByQuaternions(u_SizeScale*rotationByEuler(a_MeshPosition*size+pivot,rotation),worldRotation);}else{\n#ifdef ROTATIONOVERLIFETIME\nfloat angle=computeParticleRotationFloat(a_StartRotation0.x,age,normalizedAge);if(a_ShapePositionStartLifeTime.x!=0.0||a_ShapePositionStartLifeTime.y!=0.0){center+=(rotationByQuaternions(rotationByAxis(u_SizeScale*a_MeshPosition*size+scaledPivot,normalize(cross(vec3(0.0,0.0,1.0),vec3(a_ShapePositionStartLifeTime.xy,0.0))),angle),worldRotation));}else{vec3 axis=mix(vec3(0.0,0.0,-1.0),vec3(0.0,-1.0,0.0),float(u_Shape));\n#ifdef SHAPE\ncenter+=u_SizeScale.xzy*(rotationByQuaternions(rotationByAxis(a_MeshPosition*size+pivot,axis,angle),worldRotation));\n#else\nif(u_SimulationSpace==0)center+=rotationByAxis(u_SizeScale*a_MeshPosition*size+scaledPivot,axis,angle);else if(u_SimulationSpace==1)center+=rotationByQuaternions(u_SizeScale*rotationByAxis(a_MeshPosition*size+pivot,axis,angle),worldRotation);\n#endif\n}\n#endif\n#ifdef ROTATIONOVERLIFETIMESEPERATE\nvec3 angle=computeParticleRotationVec3(vec3(0.0,0.0,-a_StartRotation0.x),age,normalizedAge);center+=(rotationByQuaternions(rotationByEuler(u_SizeScale*a_MeshPosition*size+scaledPivot,vec3(angle.x,angle.y,angle.z)),worldRotation));\n#endif\n}\n#else\nif(u_ThreeDStartRotation!=0){center+=rotationByQuaternions(u_SizeScale*rotationByEuler(a_MeshPosition*size+pivot,a_StartRotation0),worldRotation);}else{\n#ifdef SHAPE\nif(u_SimulationSpace==0)center+=u_SizeScale*rotationByAxis(a_MeshPosition*size+pivot,vec3(0.0,-1.0,0.0),a_StartRotation0.x);else if(u_SimulationSpace==1)center+=rotationByQuaternions(u_SizeScale*rotationByAxis(a_MeshPosition*size+pivot,vec3(0.0,-1.0,0.0),a_StartRotation0.x),worldRotation);\n#else\nif(a_ShapePositionStartLifeTime.x!=0.0||a_ShapePositionStartLifeTime.y!=0.0){if(u_SimulationSpace==0)center+=rotationByAxis(u_SizeScale*a_MeshPosition*size+scaledPivot,normalize(cross(vec3(0.0,0.0,1.0),vec3(a_ShapePositionStartLifeTime.xy,0.0))),a_StartRotation0.x);else if(u_SimulationSpace==1)center+=(rotationByQuaternions(u_SizeScale*rotationByAxis(a_MeshPosition*size+pivot,normalize(cross(vec3(0.0,0.0,1.0),vec3(a_ShapePositionStartLifeTime.xy,0.0))),a_StartRotation0.x),worldRotation));}else{vec3 axis=mix(vec3(0.0,0.0,-1.0),vec3(0.0,-1.0,0.0),float(u_Shape));if(u_SimulationSpace==0)center+=u_SizeScale*rotationByAxis(a_MeshPosition*size+pivot,axis,a_StartRotation0.x);else if(u_SimulationSpace==1)center+=rotationByQuaternions(u_SizeScale*rotationByAxis(a_MeshPosition*size+pivot,axis,a_StartRotation0.x),worldRotation);}\n#endif\n}\n#endif\nv_MeshColor=a_MeshColor;\n#endif\ngl_Position=u_Projection*u_View*vec4(center,1.0);vec4 startcolor=gammaToLinear(a_StartColor);v_Color=computeParticleColor(startcolor,normalizedAge);\n#ifdef DIFFUSEMAP\nvec2 simulateUV;\n#if defined(SPHERHBILLBOARD) || defined(STRETCHEDBILLBOARD) || defined(HORIZONTALBILLBOARD) || defined(VERTICALBILLBOARD)\nsimulateUV=a_SimulationUV.xy+a_CornerTextureCoordinate.zw*a_SimulationUV.zw;v_TextureCoordinate=computeParticleUV(simulateUV,normalizedAge);\n#endif\n#ifdef RENDERMODE_MESH\nsimulateUV=a_SimulationUV.xy+a_MeshTextureCoordinate*a_SimulationUV.zw;v_TextureCoordinate=computeParticleUV(simulateUV,normalizedAge);\n#endif\nv_TextureCoordinate=TransformUV(v_TextureCoordinate,u_TilingOffset);\n#endif\n}else{gl_Position=vec4(2.0,2.0,2.0,1.0);}gl_Position=remapPositionZ(gl_Position);\n#ifdef FOG\nFogHandle(gl_Position.z);\n#endif\n}";

    var ShurikenFS = "#define SHADER_NAME ParticleFS\n#include \"Scene.glsl\";\n#include \"SceneFog.glsl\";\n#include \"Color.glsl\";\nconst vec4 c_ColorSpace=vec4(4.59479380,4.59479380,4.59479380,2.0);varying vec4 v_Color;varying vec2 v_TextureCoordinate;\n#ifdef RENDERMODE_MESH\nvarying vec4 v_MeshColor;\n#endif\nvoid main(){vec4 color;\n#ifdef RENDERMODE_MESH\ncolor=v_MeshColor;\n#else\ncolor=vec4(1.0);\n#endif\n#ifdef DIFFUSEMAP\nvec4 colorT=texture2D(u_texture,v_TextureCoordinate);\n#ifdef Gamma_u_texture\ncolorT=gammaToLinear(colorT);\n#endif\n#ifdef TINTCOLOR\ncolor*=colorT*u_Tintcolor*c_ColorSpace*v_Color;\n#else\ncolor*=colorT*v_Color;\n#endif\n#else\n#ifdef TINTCOLOR\ncolor*=u_Tintcolor*c_ColorSpace*v_Color;\n#else\ncolor*=v_Color;\n#endif\n#endif\n#ifdef ALPHATEST\nif(color.a<u_AlphaTestValue){discard;}\n#endif\n#ifdef FOG\ncolor.rgb=scenUnlitFog(color.rgb);\n#endif\ngl_FragColor=color;gl_FragColor=outputTransform(gl_FragColor);}";

    var MathGradient = "#ifdef GRAPHICS_API_GLES3\nvec2 getVec2ValueByIndexFromeVec4Array(in vec4 gradientNumbers[GRADIENT_VEC4_COUNT],in int vec2Index){int v4Index=int(floor(float(vec2Index)/2.0));int offset=(vec2Index-v4Index*2)*2;return vec2(gradientNumbers[v4Index][offset],gradientNumbers[v4Index][offset+1]);}vec2 getVec2ValueByIndexFromeVec4Array_COLORCOUNT(in vec4 gradientNumbers[COLORCOUNT_HALF],in int vec2Index){int v4Index=int(floor(float(vec2Index)/2.0));int offset=(vec2Index-v4Index*2)*2;vec4 v4Value=gradientNumbers[v4Index];return vec2(v4Value[offset],v4Value[offset+1]);}\n#endif\nfloat getCurValueFromGradientFloat(in vec4 gradientNumbers[GRADIENT_VEC4_COUNT],in float normalizedAge){float curValue;\n#ifndef GRAPHICS_API_GLES3\n#ifdef GRADIENTKEYCOUNT_8\nvec2 gradientNumbersVec2[8];gradientNumbersVec2[0]=gradientNumbers[0].xy;gradientNumbersVec2[1]=gradientNumbers[0].zw;gradientNumbersVec2[2]=gradientNumbers[1].xy;gradientNumbersVec2[3]=gradientNumbers[1].zw;gradientNumbersVec2[4]=gradientNumbers[2].xy;gradientNumbersVec2[5]=gradientNumbers[2].zw;gradientNumbersVec2[6]=gradientNumbers[3].xy;gradientNumbersVec2[7]=gradientNumbers[3].zw;\n#else\nvec2 gradientNumbersVec2[4];gradientNumbersVec2[0]=gradientNumbers[0].xy;gradientNumbersVec2[1]=gradientNumbers[0].zw;gradientNumbersVec2[2]=gradientNumbers[1].xy;gradientNumbersVec2[3]=gradientNumbers[1].zw;\n#endif\n#endif\nfor(int i=1;i<GRADIENT_KEY_COUNT;i++){vec2 gradientNumber;\n#ifdef GRAPHICS_API_GLES3\ngradientNumber=getVec2ValueByIndexFromeVec4Array(gradientNumbers,i);\n#else\ngradientNumber=gradientNumbersVec2[i];\n#endif\nfloat key=gradientNumber.x;curValue=gradientNumber.y;if(key>=normalizedAge){vec2 lastGradientNumber;\n#ifdef GRAPHICS_API_GLES3\nlastGradientNumber=getVec2ValueByIndexFromeVec4Array(gradientNumbers,i-1);\n#else\nlastGradientNumber=gradientNumbersVec2[i-1];\n#endif\nfloat lastKey=lastGradientNumber.x;float age=max((normalizedAge-lastKey),0.0)/(key-lastKey);curValue=mix(lastGradientNumber.y,gradientNumber.y,age);break;}}return curValue;}float getTotalValueFromGradientFloat(in vec4 gradientNumbers[GRADIENT_VEC4_COUNT],in float normalizedAge){\n#ifndef GRAPHICS_API_GLES3\n#ifdef GRADIENTKEYCOUNT_8\nvec2 gradientNumbersVec2[8];gradientNumbersVec2[0]=gradientNumbers[0].xy;gradientNumbersVec2[1]=gradientNumbers[0].zw;gradientNumbersVec2[2]=gradientNumbers[1].xy;gradientNumbersVec2[3]=gradientNumbers[1].zw;gradientNumbersVec2[4]=gradientNumbers[2].xy;gradientNumbersVec2[5]=gradientNumbers[2].zw;gradientNumbersVec2[6]=gradientNumbers[3].xy;gradientNumbersVec2[7]=gradientNumbers[3].zw;\n#else\nvec2 gradientNumbersVec2[4];gradientNumbersVec2[0]=gradientNumbers[0].xy;gradientNumbersVec2[1]=gradientNumbers[0].zw;gradientNumbersVec2[2]=gradientNumbers[1].xy;gradientNumbersVec2[3]=gradientNumbers[1].zw;\n#endif\n#endif\n#ifdef GRAPHICS_API_GLES3\nvec2 val=getVec2ValueByIndexFromeVec4Array(gradientNumbers,0);\n#else\nvec2 val=gradientNumbersVec2[0];\n#endif\nfloat keyTime=min(normalizedAge,val.x);float totalValue=keyTime*val.y;float lastSpeed=0.;for(int i=1;i<GRADIENT_KEY_COUNT;i++){\n#ifdef GRAPHICS_API_GLES3\nvec2 gradientNumber=getVec2ValueByIndexFromeVec4Array(gradientNumbers,i);vec2 lastGradientNumber=getVec2ValueByIndexFromeVec4Array(gradientNumbers,i-1);\n#else\nvec2 gradientNumber=gradientNumbersVec2[i];vec2 lastGradientNumber=gradientNumbersVec2[i-1];\n#endif\nfloat key=gradientNumber.x;float lastValue=lastGradientNumber.y;if(key>=normalizedAge){float lastKey=lastGradientNumber.x;float time=max((normalizedAge-lastKey),0.);float age=time/(key-lastKey);lastSpeed=mix(lastValue,gradientNumber.y,age);totalValue+=(lastValue+mix(lastValue,gradientNumber.y,age))/2.0*a_ShapePositionStartLifeTime.w*time;keyTime=normalizedAge;break;}else if(key>keyTime){totalValue+=(lastValue+gradientNumber.y)/2.0*a_ShapePositionStartLifeTime.w*(key-lastGradientNumber.x);keyTime=key;lastSpeed=gradientNumber.y;}}return totalValue+max(normalizedAge-keyTime,0.)*lastSpeed*a_ShapePositionStartLifeTime.w;}vec4 getColorFromGradient(in vec4 gradientAlphas[COLORCOUNT_HALF],in vec4 gradientColors[COLORCOUNT],in float normalizedAge,in vec4 keyRanges){\n#ifndef GRAPHICS_API_GLES3\n#ifdef COLORKEYCOUNT_8\nvec2 resoult[8];resoult[0]=gradientAlphas[0].xy;resoult[1]=gradientAlphas[0].zw;resoult[2]=gradientAlphas[1].xy;resoult[3]=gradientAlphas[1].zw;resoult[4]=gradientAlphas[2].xy;resoult[5]=gradientAlphas[2].zw;resoult[6]=gradientAlphas[3].xy;resoult[7]=gradientAlphas[3].zw;\n#else\nvec2 resoult[4];resoult[0]=gradientAlphas[0].xy;resoult[1]=gradientAlphas[0].zw;resoult[2]=gradientAlphas[1].xy;resoult[3]=gradientAlphas[1].zw;\n#endif\n#endif\nfloat alphaAge=clamp(normalizedAge,keyRanges.z,keyRanges.w);vec4 overTimeColor;for(int i=1;i<COLORCOUNT;i++){\n#ifdef GRAPHICS_API_GLES3\nvec2 gradientAlpha=getVec2ValueByIndexFromeVec4Array_COLORCOUNT(gradientAlphas,i);\n#else\nvec2 gradientAlpha=resoult[i];\n#endif\nfloat alphaKey=gradientAlpha.x;if(alphaKey>=alphaAge){\n#ifdef GRAPHICS_API_GLES3\nvec2 lastGradientAlpha=getVec2ValueByIndexFromeVec4Array_COLORCOUNT(gradientAlphas,i-1);\n#else\nvec2 lastGradientAlpha=resoult[i-1];\n#endif\nfloat lastAlphaKey=lastGradientAlpha.x;float age=clamp((alphaAge-lastAlphaKey)/(alphaKey-lastAlphaKey),0.0,1.0);overTimeColor.a=mix(lastGradientAlpha.y,gradientAlpha.y,age);break;}}float colorAge=clamp(normalizedAge,keyRanges.x,keyRanges.y);for(int i=1;i<COLORCOUNT;i++){vec4 gradientColor=gradientColors[i];float colorKey=gradientColor.x;if(colorKey>=colorAge){vec4 lastGradientColor=gradientColors[i-1];float lastColorKey=lastGradientColor.x;float age=(colorAge-lastColorKey)/(colorKey-lastColorKey);overTimeColor.rgb=mix(gradientColors[i-1].yzw,gradientColor.yzw,age);break;}}return overTimeColor;}float getFrameFromGradient(in vec4 gradientFrames[GRADIENT_VEC4_COUNT],in float normalizedAge){\n#ifndef GRAPHICS_API_GLES3\n#ifdef GRADIENTKEYCOUNT_8\nvec2 gradientNumbersVec2[8];gradientNumbersVec2[0]=gradientFrames[0].xy;gradientNumbersVec2[1]=gradientFrames[0].zw;gradientNumbersVec2[2]=gradientFrames[1].xy;gradientNumbersVec2[3]=gradientFrames[1].zw;gradientNumbersVec2[4]=gradientFrames[2].xy;gradientNumbersVec2[5]=gradientFrames[2].zw;gradientNumbersVec2[6]=gradientFrames[3].xy;gradientNumbersVec2[7]=gradientFrames[3].zw;\n#else\nvec2 gradientNumbersVec2[4];gradientNumbersVec2[0]=gradientFrames[0].xy;gradientNumbersVec2[1]=gradientFrames[0].zw;gradientNumbersVec2[2]=gradientFrames[1].xy;gradientNumbersVec2[3]=gradientFrames[1].zw;\n#endif\n#endif\nfloat overTimeFrame;for(int i=1;i<GRADIENT_KEY_COUNT;i++){\n#ifdef GRAPHICS_API_GLES3\nvec2 gradientFrame=getVec2ValueByIndexFromeVec4Array(gradientFrames,i);\n#else\nvec2 gradientFrame=gradientNumbersVec2[i];\n#endif\nfloat key=gradientFrame.x;overTimeFrame=gradientFrame.y;if(key>=normalizedAge){\n#ifdef GRAPHICS_API_GLES3\nvec2 lastGradientFrame=getVec2ValueByIndexFromeVec4Array(gradientFrames,i-1);\n#else\nvec2 lastGradientFrame=gradientNumbersVec2[i-1];\n#endif\nfloat lastKey=lastGradientFrame.x;float age=max((normalizedAge-lastKey),0.)/(key-lastKey);overTimeFrame=mix(lastGradientFrame.y,gradientFrame.y,age);break;}}return floor(overTimeFrame);}";

    var ParticleSpriteVS = "uniform float u_CurrentTime;uniform vec3 u_Gravity;uniform vec2 u_DragConstanct;uniform vec3 u_WorldPosition;uniform vec4 u_WorldRotation;uniform int u_ThreeDStartRotation;uniform int u_Shape;uniform int u_ScalingMode;uniform vec3 u_PositionScale;uniform vec3 u_SizeScale;uniform float u_StretchedBillboardLengthScale;uniform float u_StretchedBillboardSpeedScale;uniform int u_SimulationSpace;\n#ifdef GRADIENTKEYCOUNT_8\n#define GRADIENT_VEC4_COUNT 4\n#define GRADIENT_KEY_COUNT 8\n#else\n#define GRADIENT_VEC4_COUNT 2\n#define GRADIENT_KEY_COUNT 4\n#endif\n#if defined(VELOCITYOVERLIFETIMECONSTANT) || defined(VELOCITYOVERLIFETIMECURVE) || defined(VELOCITYOVERLIFETIMERANDOMCONSTANT) || defined(VELOCITYOVERLIFETIMERANDOMCURVE)\nuniform int u_VOLSpaceType;\n#endif\n#if defined(VELOCITYOVERLIFETIMECONSTANT) || defined(VELOCITYOVERLIFETIMERANDOMCONSTANT)\nuniform vec3 u_VOLVelocityConst;\n#endif\n#if defined(VELOCITYOVERLIFETIMECURVE) || defined(VELOCITYOVERLIFETIMERANDOMCURVE)\n#ifdef GRADIENTKEYCOUNT_8\nuniform vec4 u_VOLVelocityGradientX[4];uniform vec4 u_VOLVelocityGradientY[4];uniform vec4 u_VOLVelocityGradientZ[4];\n#else\nuniform vec4 u_VOLVelocityGradientX[2];uniform vec4 u_VOLVelocityGradientY[2];uniform vec4 u_VOLVelocityGradientZ[2];\n#endif\n#endif\n#ifdef VELOCITYOVERLIFETIMERANDOMCONSTANT\nuniform vec3 u_VOLVelocityConstMax;\n#endif\n#ifdef VELOCITYOVERLIFETIMERANDOMCURVE\n#ifdef GRADIENTKEYCOUNT_8\nuniform vec4 u_VOLVelocityGradientMaxX[4];uniform vec4 u_VOLVelocityGradientMaxY[4];uniform vec4 u_VOLVelocityGradientMaxZ[4];\n#else\nuniform vec4 u_VOLVelocityGradientMaxX[2];uniform vec4 u_VOLVelocityGradientMaxY[2];uniform vec4 u_VOLVelocityGradientMaxZ[2];\n#endif\n#endif\n#ifdef COLORKEYCOUNT_8\n#define COLORCOUNT 8\n#define COLORCOUNT_HALF 4\n#else\n#define COLORCOUNT 4\n#define COLORCOUNT_HALF 2\n#endif\n#ifdef COLOROVERLIFETIME\nuniform vec4 u_ColorOverLifeGradientColors[COLORCOUNT];uniform vec4 u_ColorOverLifeGradientAlphas[COLORCOUNT_HALF];uniform vec4 u_ColorOverLifeGradientRanges;\n#endif\n#ifdef RANDOMCOLOROVERLIFETIME\nuniform vec4 u_ColorOverLifeGradientColors[COLORCOUNT];uniform vec4 u_ColorOverLifeGradientAlphas[COLORCOUNT_HALF];uniform vec4 u_ColorOverLifeGradientRanges;uniform vec4 u_MaxColorOverLifeGradientColors[COLORCOUNT];uniform vec4 u_MaxColorOverLifeGradientAlphas[COLORCOUNT_HALF];uniform vec4 u_MaxColorOverLifeGradientRanges;\n#endif\n#if defined(SIZEOVERLIFETIMECURVE) || defined(SIZEOVERLIFETIMERANDOMCURVES)\n#ifdef GRADIENTKEYCOUNT_8\nuniform vec4 u_SOLSizeGradient[4];\n#else\nuniform vec4 u_SOLSizeGradient[2];\n#endif\n#endif\n#ifdef SIZEOVERLIFETIMERANDOMCURVES\n#ifdef GRADIENTKEYCOUNT_8\nuniform vec4 u_SOLSizeGradientMax[4];\n#else\nuniform vec4 u_SOLSizeGradientMax[2];\n#endif\n#endif\n#if defined(SIZEOVERLIFETIMECURVESEPERATE) || defined(SIZEOVERLIFETIMERANDOMCURVESSEPERATE)\n#ifdef GRADIENTKEYCOUNT_8\nuniform vec4 u_SOLSizeGradientX[4];uniform vec4 u_SOLSizeGradientY[4];uniform vec4 u_SOLSizeGradientZ[4];\n#else\nuniform vec4 u_SOLSizeGradientX[2];uniform vec4 u_SOLSizeGradientY[2];uniform vec4 u_SOLSizeGradientZ[2];\n#endif\n#endif\n#ifdef SIZEOVERLIFETIMERANDOMCURVESSEPERATE\n#ifdef GRADIENTKEYCOUNT_8\nuniform vec4 u_SOLSizeGradientMaxX[4];uniform vec4 u_SOLSizeGradientMaxY[4];uniform vec4 u_SOLSizeGradientMaxZ[4];\n#else\nuniform vec4 u_SOLSizeGradientMaxX[2];uniform vec4 u_SOLSizeGradientMaxY[2];uniform vec4 u_SOLSizeGradientMaxZ[2];\n#endif\n#endif\n#ifdef ROTATIONOVERLIFETIME\n#if defined(ROTATIONOVERLIFETIMECONSTANT) || defined(ROTATIONOVERLIFETIMERANDOMCONSTANTS)\nuniform float u_ROLAngularVelocityConst;\n#endif\n#ifdef ROTATIONOVERLIFETIMERANDOMCONSTANTS\nuniform float u_ROLAngularVelocityConstMax;\n#endif\n#if defined(ROTATIONOVERLIFETIMECURVE) || defined(ROTATIONOVERLIFETIMERANDOMCURVES)\n#ifdef GRADIENTKEYCOUNT_8\nuniform vec4 u_ROLAngularVelocityGradient[4];\n#else\nuniform vec4 u_ROLAngularVelocityGradient[2];\n#endif\n#endif\n#ifdef ROTATIONOVERLIFETIMERANDOMCURVES\n#ifdef GRADIENTKEYCOUNT_8\nuniform vec4 u_ROLAngularVelocityGradientMax[4];\n#else\nuniform vec4 u_ROLAngularVelocityGradientMax[2];\n#endif\n#endif\n#endif\n#ifdef ROTATIONOVERLIFETIMESEPERATE\n#if defined(ROTATIONOVERLIFETIMECONSTANT) || defined(ROTATIONOVERLIFETIMERANDOMCONSTANTS)\nuniform vec3 u_ROLAngularVelocityConstSeprarate;\n#endif\n#ifdef ROTATIONOVERLIFETIMERANDOMCONSTANTS\nuniform vec3 u_ROLAngularVelocityConstMaxSeprarate;\n#endif\n#if defined(ROTATIONOVERLIFETIMECURVE) || defined(ROTATIONOVERLIFETIMERANDOMCURVES)\n#ifdef GRADIENTKEYCOUNT_8\nuniform vec4 u_ROLAngularVelocityGradientX[4];uniform vec4 u_ROLAngularVelocityGradientY[4];uniform vec4 u_ROLAngularVelocityGradientZ[4];\n#else\nuniform vec4 u_ROLAngularVelocityGradientX[2];uniform vec4 u_ROLAngularVelocityGradientY[2];uniform vec4 u_ROLAngularVelocityGradientZ[2];\n#endif\n#endif\n#ifdef ROTATIONOVERLIFETIMERANDOMCURVES\n#ifdef GRADIENTKEYCOUNT_8\nuniform vec4 u_ROLAngularVelocityGradientMaxX[4];uniform vec4 u_ROLAngularVelocityGradientMaxY[4];uniform vec4 u_ROLAngularVelocityGradientMaxZ[4];\n#else\nuniform vec4 u_ROLAngularVelocityGradientMaxX[2];uniform vec4 u_ROLAngularVelocityGradientMaxY[2];uniform vec4 u_ROLAngularVelocityGradientMaxZ[2];\n#endif\n#endif\n#endif\n#if defined(TEXTURESHEETANIMATIONCURVE) || defined(TEXTURESHEETANIMATIONRANDOMCURVE)\nuniform float u_TSACycles;uniform vec2 u_TSASubUVLength;\n#ifdef GRADIENTKEYCOUNT_8\nuniform vec4 u_TSAGradientUVs[4];\n#else\nuniform vec4 u_TSAGradientUVs[2];\n#endif\n#endif\n#ifdef TEXTURESHEETANIMATIONRANDOMCURVE\n#ifdef GRADIENTKEYCOUNT_8\nuniform vec4 u_TSAMaxGradientUVs[4];\n#else\nuniform vec4 u_TSAMaxGradientUVs[2];\n#endif\n#endif\nuniform vec3 u_Pivot;";

    class VertexShuriKenParticle {
        constructor() {
        }
    }
    VertexShuriKenParticle.PARTICLE_DIRECTIONTIME = 0;
    VertexShuriKenParticle.PARTICLE_POSITION0 = 1;
    VertexShuriKenParticle.PARTICLE_COLOR0 = 2;
    VertexShuriKenParticle.PARTICLE_TEXTURECOORDINATE0 = 3;
    VertexShuriKenParticle.PARTICLE_SHAPEPOSITIONSTARTLIFETIME = 4;
    VertexShuriKenParticle.PARTICLE_CORNERTEXTURECOORDINATE0 = 5;
    VertexShuriKenParticle.PARTICLE_STARTCOLOR0 = 6;
    VertexShuriKenParticle.PARTICLE_ENDCOLOR0 = 7;
    VertexShuriKenParticle.PARTICLE_STARTSIZE = 8;
    VertexShuriKenParticle.PARTICLE_STARTROTATION = 9;
    VertexShuriKenParticle.PARTICLE_STARTSPEED = 10;
    VertexShuriKenParticle.PARTICLE_RANDOM0 = 11;
    VertexShuriKenParticle.PARTICLE_RANDOM1 = 12;
    VertexShuriKenParticle.PARTICLE_SIMULATIONWORLDPOSTION = 13;
    VertexShuriKenParticle.PARTICLE_SIMULATIONWORLDROTATION = 14;
    VertexShuriKenParticle.PARTICLE_SIMULATIONUV = 15;

    class ParticleShuriKenShaderInit {
        static init() {
            Laya.Shader3D.addInclude("MathGradient.glsl", MathGradient);
            Laya.Shader3D.addInclude("particleShuriKenSpriteVS.glsl", ParticleSpriteVS);
            let attributeMap = {
                'a_CornerTextureCoordinate': [VertexShuriKenParticle.PARTICLE_CORNERTEXTURECOORDINATE0, Laya.ShaderDataType.Vector4],
                'a_MeshPosition': [VertexShuriKenParticle.PARTICLE_POSITION0, Laya.ShaderDataType.Vector3],
                'a_MeshColor': [VertexShuriKenParticle.PARTICLE_COLOR0, Laya.ShaderDataType.Vector4],
                'a_MeshTextureCoordinate': [VertexShuriKenParticle.PARTICLE_TEXTURECOORDINATE0, Laya.ShaderDataType.Vector2],
                'a_ShapePositionStartLifeTime': [VertexShuriKenParticle.PARTICLE_SHAPEPOSITIONSTARTLIFETIME, Laya.ShaderDataType.Vector4],
                'a_DirectionTime': [VertexShuriKenParticle.PARTICLE_DIRECTIONTIME, Laya.ShaderDataType.Vector4],
                'a_StartColor': [VertexShuriKenParticle.PARTICLE_STARTCOLOR0, Laya.ShaderDataType.Vector4],
                'a_StartSize': [VertexShuriKenParticle.PARTICLE_STARTSIZE, Laya.ShaderDataType.Vector3],
                'a_StartRotation0': [VertexShuriKenParticle.PARTICLE_STARTROTATION, Laya.ShaderDataType.Vector3],
                'a_StartSpeed': [VertexShuriKenParticle.PARTICLE_STARTSPEED, Laya.ShaderDataType.Float],
                'a_Random0': [VertexShuriKenParticle.PARTICLE_RANDOM0, Laya.ShaderDataType.Vector4],
                'a_Random1': [VertexShuriKenParticle.PARTICLE_RANDOM1, Laya.ShaderDataType.Vector4],
                'a_SimulationWorldPostion': [VertexShuriKenParticle.PARTICLE_SIMULATIONWORLDPOSTION, Laya.ShaderDataType.Vector3],
                'a_SimulationWorldRotation': [VertexShuriKenParticle.PARTICLE_SIMULATIONWORLDROTATION, Laya.ShaderDataType.Vector4],
                'a_SimulationUV': [VertexShuriKenParticle.PARTICLE_SIMULATIONUV, Laya.ShaderDataType.Vector4]
            };
            let uniformMap = {
                "u_Tintcolor": Laya.ShaderDataType.Color,
                "u_texture": Laya.ShaderDataType.Texture2D,
                "u_TilingOffset": Laya.ShaderDataType.Vector4,
                "u_AlphaTestValue": Laya.ShaderDataType.Float,
            };
            let defaultValue = {
                "u_Tintcolor": new Laya.Color(0.5, 0.5, 0.5, 0.5),
                "u_TilingOffset": new Laya.Vector4(1, 1, 0, 0),
                "u_AlphaTestValue": 0.5
            };
            let shader = Laya.Shader3D.add("PARTICLESHURIKEN", false, false);
            let subShader = new Laya.SubShader(attributeMap, uniformMap, defaultValue);
            shader.addSubShader(subShader);
            shader.shaderType = Laya.ShaderFeatureType.Effect;
            subShader.addShaderPass(ShurikenVS, ShurikenFS);
        }
    }

    class ShuriKenParticle3DShaderDeclaration {
        static __init__() {
            let mulDefineMode = ShuriKenParticle3DShaderDeclaration.mulShaderDefineMode;
            ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_RENDERMODE_BILLBOARD = Laya.Shader3D.getDefineByName("SPHERHBILLBOARD");
            ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_RENDERMODE_STRETCHEDBILLBOARD = Laya.Shader3D.getDefineByName("STRETCHEDBILLBOARD");
            ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_RENDERMODE_HORIZONTALBILLBOARD = Laya.Shader3D.getDefineByName("HORIZONTALBILLBOARD");
            ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_RENDERMODE_VERTICALBILLBOARD = Laya.Shader3D.getDefineByName("VERTICALBILLBOARD");
            ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_COLORKEYCOUNT_8 = Laya.Shader3D.getDefineByName("COLORKEYCOUNT_8");
            ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_GRADIENTKEYCOUNT_8 = Laya.Shader3D.getDefineByName("GRADIENTKEYCOUNT_8");
            mulDefineMode && (ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_COLOROVERLIFETIME = Laya.Shader3D.getDefineByName("COLOROVERLIFETIME"));
            ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_RANDOMCOLOROVERLIFETIME = Laya.Shader3D.getDefineByName("RANDOMCOLOROVERLIFETIME");
            mulDefineMode && (ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_VELOCITYOVERLIFETIMECONSTANT = Laya.Shader3D.getDefineByName("VELOCITYOVERLIFETIMECONSTANT"));
            mulDefineMode && (ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_VELOCITYOVERLIFETIMECURVE = Laya.Shader3D.getDefineByName("VELOCITYOVERLIFETIMECURVE"));
            mulDefineMode && (ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_VELOCITYOVERLIFETIMERANDOMCONSTANT = Laya.Shader3D.getDefineByName("VELOCITYOVERLIFETIMERANDOMCONSTANT"));
            ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_VELOCITYOVERLIFETIMERANDOMCURVE = Laya.Shader3D.getDefineByName("VELOCITYOVERLIFETIMERANDOMCURVE");
            mulDefineMode && (ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_TEXTURESHEETANIMATIONCURVE = Laya.Shader3D.getDefineByName("TEXTURESHEETANIMATIONCURVE"));
            ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_TEXTURESHEETANIMATIONRANDOMCURVE = Laya.Shader3D.getDefineByName("TEXTURESHEETANIMATIONRANDOMCURVE");
            ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_ROTATIONOVERLIFETIME = Laya.Shader3D.getDefineByName("ROTATIONOVERLIFETIME");
            ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_ROTATIONOVERLIFETIMESEPERATE = Laya.Shader3D.getDefineByName("ROTATIONOVERLIFETIMESEPERATE");
            mulDefineMode && (ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_ROTATIONOVERLIFETIMECONSTANT = Laya.Shader3D.getDefineByName("ROTATIONOVERLIFETIMECONSTANT"));
            mulDefineMode && (ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_ROTATIONOVERLIFETIMECURVE = Laya.Shader3D.getDefineByName("ROTATIONOVERLIFETIMECURVE"));
            mulDefineMode && (ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_ROTATIONOVERLIFETIMERANDOMCONSTANTS = Laya.Shader3D.getDefineByName("ROTATIONOVERLIFETIMERANDOMCONSTANTS"));
            mulDefineMode && (ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_ROTATIONOVERLIFETIMERANDOMCURVES = Laya.Shader3D.getDefineByName("ROTATIONOVERLIFETIMERANDOMCURVES"));
            mulDefineMode && (ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_SIZEOVERLIFETIMECURVE = Laya.Shader3D.getDefineByName("SIZEOVERLIFETIMECURVE"));
            mulDefineMode && (ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_SIZEOVERLIFETIMECURVESEPERATE = Laya.Shader3D.getDefineByName("SIZEOVERLIFETIMECURVESEPERATE"));
            ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_SIZEOVERLIFETIMERANDOMCURVES = Laya.Shader3D.getDefineByName("SIZEOVERLIFETIMERANDOMCURVES");
            ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_SIZEOVERLIFETIMERANDOMCURVESSEPERATE = Laya.Shader3D.getDefineByName("SIZEOVERLIFETIMERANDOMCURVESSEPERATE");
            ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_RENDERMODE_MESH = Laya.Shader3D.getDefineByName("RENDERMODE_MESH");
            mulDefineMode && (ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_SHAPE = Laya.Shader3D.getDefineByName("SHAPE"));
            ShuriKenParticle3DShaderDeclaration.WORLDPOSITION = Laya.Shader3D.propertyNameToID("u_WorldPosition");
            ShuriKenParticle3DShaderDeclaration.WORLDROTATION = Laya.Shader3D.propertyNameToID("u_WorldRotation");
            ShuriKenParticle3DShaderDeclaration.POSITIONSCALE = Laya.Shader3D.propertyNameToID("u_PositionScale");
            ShuriKenParticle3DShaderDeclaration.SIZESCALE = Laya.Shader3D.propertyNameToID("u_SizeScale");
            ShuriKenParticle3DShaderDeclaration.SCALINGMODE = Laya.Shader3D.propertyNameToID("u_ScalingMode");
            ShuriKenParticle3DShaderDeclaration.GRAVITY = Laya.Shader3D.propertyNameToID("u_Gravity");
            ShuriKenParticle3DShaderDeclaration.THREEDSTARTROTATION = Laya.Shader3D.propertyNameToID("u_ThreeDStartRotation");
            ShuriKenParticle3DShaderDeclaration.SHAPE = Laya.Shader3D.propertyNameToID("u_Shape");
            ShuriKenParticle3DShaderDeclaration.STRETCHEDBILLBOARDLENGTHSCALE = Laya.Shader3D.propertyNameToID("u_StretchedBillboardLengthScale");
            ShuriKenParticle3DShaderDeclaration.STRETCHEDBILLBOARDSPEEDSCALE = Laya.Shader3D.propertyNameToID("u_StretchedBillboardSpeedScale");
            ShuriKenParticle3DShaderDeclaration.SIMULATIONSPACE = Laya.Shader3D.propertyNameToID("u_SimulationSpace");
            ShuriKenParticle3DShaderDeclaration.CURRENTTIME = Laya.Shader3D.propertyNameToID("u_CurrentTime");
            ShuriKenParticle3DShaderDeclaration.DRAG = Laya.Shader3D.propertyNameToID("u_DragConstanct");
            ShuriKenParticle3DShaderDeclaration.PIVOT = Laya.Shader3D.propertyNameToID("u_Pivot");
            mulDefineMode && (ShuriKenParticle3DShaderDeclaration.VOLVELOCITYCONST = Laya.Shader3D.propertyNameToID("u_VOLVelocityConst"));
            ShuriKenParticle3DShaderDeclaration.VOLVELOCITYGRADIENTX = Laya.Shader3D.propertyNameToID("u_VOLVelocityGradientX");
            ShuriKenParticle3DShaderDeclaration.VOLVELOCITYGRADIENTY = Laya.Shader3D.propertyNameToID("u_VOLVelocityGradientY");
            ShuriKenParticle3DShaderDeclaration.VOLVELOCITYGRADIENTZ = Laya.Shader3D.propertyNameToID("u_VOLVelocityGradientZ");
            mulDefineMode && (ShuriKenParticle3DShaderDeclaration.VOLVELOCITYCONSTMAX = Laya.Shader3D.propertyNameToID("u_VOLVelocityConstMax"));
            ShuriKenParticle3DShaderDeclaration.VOLVELOCITYGRADIENTXMAX = Laya.Shader3D.propertyNameToID("u_VOLVelocityGradientMaxX");
            ShuriKenParticle3DShaderDeclaration.VOLVELOCITYGRADIENTYMAX = Laya.Shader3D.propertyNameToID("u_VOLVelocityGradientMaxY");
            ShuriKenParticle3DShaderDeclaration.VOLVELOCITYGRADIENTZMAX = Laya.Shader3D.propertyNameToID("u_VOLVelocityGradientMaxZ");
            ShuriKenParticle3DShaderDeclaration.VOLSPACETYPE = Laya.Shader3D.propertyNameToID("u_VOLSpaceType");
            ShuriKenParticle3DShaderDeclaration.COLOROVERLIFEGRADIENTALPHAS = Laya.Shader3D.propertyNameToID("u_ColorOverLifeGradientAlphas");
            ShuriKenParticle3DShaderDeclaration.COLOROVERLIFEGRADIENTCOLORS = Laya.Shader3D.propertyNameToID("u_ColorOverLifeGradientColors");
            ShuriKenParticle3DShaderDeclaration.COLOROVERLIFEGRADIENTRANGES = Laya.Shader3D.propertyNameToID("u_ColorOverLifeGradientRanges");
            ShuriKenParticle3DShaderDeclaration.MAXCOLOROVERLIFEGRADIENTALPHAS = Laya.Shader3D.propertyNameToID("u_MaxColorOverLifeGradientAlphas");
            ShuriKenParticle3DShaderDeclaration.MAXCOLOROVERLIFEGRADIENTCOLORS = Laya.Shader3D.propertyNameToID("u_MaxColorOverLifeGradientColors");
            ShuriKenParticle3DShaderDeclaration.MAXCOLOROVERLIFEGRADIENTRANGES = Laya.Shader3D.propertyNameToID("u_MaxColorOverLifeGradientRanges");
            ShuriKenParticle3DShaderDeclaration.SOLSIZEGRADIENT = Laya.Shader3D.propertyNameToID("u_SOLSizeGradient");
            ShuriKenParticle3DShaderDeclaration.SOLSIZEGRADIENTX = Laya.Shader3D.propertyNameToID("u_SOLSizeGradientX");
            ShuriKenParticle3DShaderDeclaration.SOLSIZEGRADIENTY = Laya.Shader3D.propertyNameToID("u_SOLSizeGradientY");
            ShuriKenParticle3DShaderDeclaration.SOLSizeGradientZ = Laya.Shader3D.propertyNameToID("u_SOLSizeGradientZ");
            ShuriKenParticle3DShaderDeclaration.SOLSizeGradientMax = Laya.Shader3D.propertyNameToID("u_SOLSizeGradientMax");
            ShuriKenParticle3DShaderDeclaration.SOLSIZEGRADIENTXMAX = Laya.Shader3D.propertyNameToID("u_SOLSizeGradientMaxX");
            ShuriKenParticle3DShaderDeclaration.SOLSIZEGRADIENTYMAX = Laya.Shader3D.propertyNameToID("u_SOLSizeGradientMaxY");
            ShuriKenParticle3DShaderDeclaration.SOLSizeGradientZMAX = Laya.Shader3D.propertyNameToID("u_SOLSizeGradientMaxZ");
            mulDefineMode && (ShuriKenParticle3DShaderDeclaration.ROLANGULARVELOCITYCONST = Laya.Shader3D.propertyNameToID("u_ROLAngularVelocityConst"));
            mulDefineMode && (ShuriKenParticle3DShaderDeclaration.ROLANGULARVELOCITYCONSTSEPRARATE = Laya.Shader3D.propertyNameToID("u_ROLAngularVelocityConstSeprarate"));
            ShuriKenParticle3DShaderDeclaration.ROLANGULARVELOCITYGRADIENT = Laya.Shader3D.propertyNameToID("u_ROLAngularVelocityGradient");
            ShuriKenParticle3DShaderDeclaration.ROLANGULARVELOCITYGRADIENTX = Laya.Shader3D.propertyNameToID("u_ROLAngularVelocityGradientX");
            ShuriKenParticle3DShaderDeclaration.ROLANGULARVELOCITYGRADIENTY = Laya.Shader3D.propertyNameToID("u_ROLAngularVelocityGradientY");
            ShuriKenParticle3DShaderDeclaration.ROLANGULARVELOCITYGRADIENTZ = Laya.Shader3D.propertyNameToID("u_ROLAngularVelocityGradientZ");
            mulDefineMode && (ShuriKenParticle3DShaderDeclaration.ROLANGULARVELOCITYCONSTMAX = Laya.Shader3D.propertyNameToID("u_ROLAngularVelocityConstMax"));
            mulDefineMode && (ShuriKenParticle3DShaderDeclaration.ROLANGULARVELOCITYCONSTMAXSEPRARATE = Laya.Shader3D.propertyNameToID("u_ROLAngularVelocityConstMaxSeprarate"));
            ShuriKenParticle3DShaderDeclaration.ROLANGULARVELOCITYGRADIENTMAX = Laya.Shader3D.propertyNameToID("u_ROLAngularVelocityGradientMax");
            ShuriKenParticle3DShaderDeclaration.ROLANGULARVELOCITYGRADIENTXMAX = Laya.Shader3D.propertyNameToID("u_ROLAngularVelocityGradientMaxX");
            ShuriKenParticle3DShaderDeclaration.ROLANGULARVELOCITYGRADIENTYMAX = Laya.Shader3D.propertyNameToID("u_ROLAngularVelocityGradientMaxY");
            ShuriKenParticle3DShaderDeclaration.ROLANGULARVELOCITYGRADIENTZMAX = Laya.Shader3D.propertyNameToID("u_ROLAngularVelocityGradientMaxZ");
            ShuriKenParticle3DShaderDeclaration.TEXTURESHEETANIMATIONCYCLES = Laya.Shader3D.propertyNameToID("u_TSACycles");
            ShuriKenParticle3DShaderDeclaration.TEXTURESHEETANIMATIONSUBUVLENGTH = Laya.Shader3D.propertyNameToID("u_TSASubUVLength");
            ShuriKenParticle3DShaderDeclaration.TEXTURESHEETANIMATIONGRADIENTUVS = Laya.Shader3D.propertyNameToID("u_TSAGradientUVs");
            ShuriKenParticle3DShaderDeclaration.TEXTURESHEETANIMATIONGRADIENTMAXUVS = Laya.Shader3D.propertyNameToID("u_TSAMaxGradientUVs");
            let uniformMap = Laya.LayaGL.renderDeviceFactory.createGlobalUniformMap("ShurikenSprite3D");
            uniformMap.addShaderUniform(ShuriKenParticle3DShaderDeclaration.WORLDPOSITION, 'u_WorldPosition', Laya.ShaderDataType.Vector3),
                uniformMap.addShaderUniform(ShuriKenParticle3DShaderDeclaration.WORLDROTATION, 'u_WorldRotation', Laya.ShaderDataType.Vector4);
            uniformMap.addShaderUniform(ShuriKenParticle3DShaderDeclaration.POSITIONSCALE, 'u_PositionScale', Laya.ShaderDataType.Vector3);
            uniformMap.addShaderUniform(ShuriKenParticle3DShaderDeclaration.SIZESCALE, 'u_SizeScale', Laya.ShaderDataType.Vector3);
            uniformMap.addShaderUniform(ShuriKenParticle3DShaderDeclaration.SCALINGMODE, 'u_ScalingMode', Laya.ShaderDataType.Int);
            uniformMap.addShaderUniform(ShuriKenParticle3DShaderDeclaration.GRAVITY, 'u_Gravity', Laya.ShaderDataType.Vector3);
            uniformMap.addShaderUniform(ShuriKenParticle3DShaderDeclaration.THREEDSTARTROTATION, 'u_ThreeDStartRotation', Laya.ShaderDataType.Int);
            uniformMap.addShaderUniform(ShuriKenParticle3DShaderDeclaration.STRETCHEDBILLBOARDLENGTHSCALE, 'u_StretchedBillboardLengthScale', Laya.ShaderDataType.Float);
            uniformMap.addShaderUniform(ShuriKenParticle3DShaderDeclaration.STRETCHEDBILLBOARDSPEEDSCALE, 'u_StretchedBillboardSpeedScale', Laya.ShaderDataType.Float);
            uniformMap.addShaderUniform(ShuriKenParticle3DShaderDeclaration.SIMULATIONSPACE, 'u_SimulationSpace', Laya.ShaderDataType.Int);
            uniformMap.addShaderUniform(ShuriKenParticle3DShaderDeclaration.CURRENTTIME, 'u_CurrentTime', Laya.ShaderDataType.Float);
            uniformMap.addShaderUniform(ShuriKenParticle3DShaderDeclaration.SHAPE, 'u_Shape', Laya.ShaderDataType.Float);
            uniformMap.addShaderUniformArray(ShuriKenParticle3DShaderDeclaration.COLOROVERLIFEGRADIENTALPHAS, 'u_ColorOverLifeGradientAlphas', Laya.ShaderDataType.Vector4, 4);
            uniformMap.addShaderUniformArray(ShuriKenParticle3DShaderDeclaration.COLOROVERLIFEGRADIENTCOLORS, 'u_ColorOverLifeGradientColors', Laya.ShaderDataType.Vector4, 8);
            uniformMap.addShaderUniform(ShuriKenParticle3DShaderDeclaration.COLOROVERLIFEGRADIENTRANGES, 'u_ColorOverLifeGradientRanges', Laya.ShaderDataType.Vector4);
            uniformMap.addShaderUniformArray(ShuriKenParticle3DShaderDeclaration.MAXCOLOROVERLIFEGRADIENTALPHAS, 'u_MaxColorOverLifeGradientAlphas', Laya.ShaderDataType.Vector4, 4);
            uniformMap.addShaderUniformArray(ShuriKenParticle3DShaderDeclaration.MAXCOLOROVERLIFEGRADIENTCOLORS, 'u_MaxColorOverLifeGradientColors', Laya.ShaderDataType.Vector4, 8);
            uniformMap.addShaderUniform(ShuriKenParticle3DShaderDeclaration.MAXCOLOROVERLIFEGRADIENTRANGES, 'u_MaxColorOverLifeGradientRanges', Laya.ShaderDataType.Vector4);
            mulDefineMode && (uniformMap.addShaderUniform(ShuriKenParticle3DShaderDeclaration.VOLVELOCITYCONST, 'u_VOLVelocityConst', Laya.ShaderDataType.Vector3));
            uniformMap.addShaderUniformArray(ShuriKenParticle3DShaderDeclaration.VOLVELOCITYGRADIENTX, 'u_VOLVelocityGradientX', Laya.ShaderDataType.Vector4, 4);
            uniformMap.addShaderUniformArray(ShuriKenParticle3DShaderDeclaration.VOLVELOCITYGRADIENTY, 'u_VOLVelocityGradientY', Laya.ShaderDataType.Vector4, 4);
            uniformMap.addShaderUniformArray(ShuriKenParticle3DShaderDeclaration.VOLVELOCITYGRADIENTZ, 'u_VOLVelocityGradientZ', Laya.ShaderDataType.Vector4, 4);
            mulDefineMode && (uniformMap.addShaderUniform(ShuriKenParticle3DShaderDeclaration.VOLVELOCITYCONSTMAX, 'u_VOLVelocityConstMax', Laya.ShaderDataType.Vector3));
            uniformMap.addShaderUniformArray(ShuriKenParticle3DShaderDeclaration.VOLVELOCITYGRADIENTXMAX, 'u_VOLVelocityGradientMaxX', Laya.ShaderDataType.Vector4, 4);
            uniformMap.addShaderUniformArray(ShuriKenParticle3DShaderDeclaration.VOLVELOCITYGRADIENTYMAX, 'u_VOLVelocityGradientMaxY', Laya.ShaderDataType.Vector4, 4);
            uniformMap.addShaderUniformArray(ShuriKenParticle3DShaderDeclaration.VOLVELOCITYGRADIENTZMAX, 'u_VOLVelocityGradientMaxZ', Laya.ShaderDataType.Vector4, 4);
            uniformMap.addShaderUniform(ShuriKenParticle3DShaderDeclaration.VOLSPACETYPE, 'u_VOLSpaceType', Laya.ShaderDataType.Int);
            uniformMap.addShaderUniformArray(ShuriKenParticle3DShaderDeclaration.SOLSIZEGRADIENT, 'u_SOLSizeGradient', Laya.ShaderDataType.Vector4, 4);
            uniformMap.addShaderUniformArray(ShuriKenParticle3DShaderDeclaration.SOLSIZEGRADIENTX, 'u_SOLSizeGradientX', Laya.ShaderDataType.Vector4, 4);
            uniformMap.addShaderUniformArray(ShuriKenParticle3DShaderDeclaration.SOLSIZEGRADIENTY, 'u_SOLSizeGradientY', Laya.ShaderDataType.Vector4, 4);
            uniformMap.addShaderUniformArray(ShuriKenParticle3DShaderDeclaration.SOLSizeGradientZ, 'u_SOLSizeGradientZ', Laya.ShaderDataType.Vector4, 4);
            uniformMap.addShaderUniformArray(ShuriKenParticle3DShaderDeclaration.SOLSizeGradientMax, 'u_SOLSizeGradientMax', Laya.ShaderDataType.Vector4, 4);
            uniformMap.addShaderUniformArray(ShuriKenParticle3DShaderDeclaration.SOLSIZEGRADIENTXMAX, 'u_SOLSizeGradientMaxX', Laya.ShaderDataType.Vector4, 4);
            uniformMap.addShaderUniformArray(ShuriKenParticle3DShaderDeclaration.SOLSIZEGRADIENTYMAX, 'u_SOLSizeGradientMaxY', Laya.ShaderDataType.Vector4, 4);
            uniformMap.addShaderUniformArray(ShuriKenParticle3DShaderDeclaration.SOLSizeGradientZMAX, 'u_SOLSizeGradientMaxZ', Laya.ShaderDataType.Vector4, 4);
            mulDefineMode && (uniformMap.addShaderUniform(ShuriKenParticle3DShaderDeclaration.ROLANGULARVELOCITYCONST, 'u_ROLAngularVelocityConst', Laya.ShaderDataType.Float));
            mulDefineMode && (uniformMap.addShaderUniform(ShuriKenParticle3DShaderDeclaration.ROLANGULARVELOCITYCONSTSEPRARATE, 'u_ROLAngularVelocityConstSeprarate', Laya.ShaderDataType.Vector3));
            uniformMap.addShaderUniformArray(ShuriKenParticle3DShaderDeclaration.ROLANGULARVELOCITYGRADIENT, 'u_ROLAngularVelocityGradient', Laya.ShaderDataType.Vector4, 4);
            uniformMap.addShaderUniformArray(ShuriKenParticle3DShaderDeclaration.ROLANGULARVELOCITYGRADIENTX, 'u_ROLAngularVelocityGradientX', Laya.ShaderDataType.Vector4, 4);
            uniformMap.addShaderUniformArray(ShuriKenParticle3DShaderDeclaration.ROLANGULARVELOCITYGRADIENTY, 'u_ROLAngularVelocityGradientY', Laya.ShaderDataType.Vector4, 4);
            uniformMap.addShaderUniformArray(ShuriKenParticle3DShaderDeclaration.ROLANGULARVELOCITYGRADIENTZ, 'u_ROLAngularVelocityGradientZ', Laya.ShaderDataType.Vector4, 4);
            mulDefineMode && (uniformMap.addShaderUniform(ShuriKenParticle3DShaderDeclaration.ROLANGULARVELOCITYCONSTMAX, 'u_ROLAngularVelocityConstMax', Laya.ShaderDataType.Float));
            mulDefineMode && (uniformMap.addShaderUniform(ShuriKenParticle3DShaderDeclaration.ROLANGULARVELOCITYCONSTMAXSEPRARATE, 'u_ROLAngularVelocityConstMaxSeprarate', Laya.ShaderDataType.Vector3));
            uniformMap.addShaderUniformArray(ShuriKenParticle3DShaderDeclaration.ROLANGULARVELOCITYGRADIENTMAX, 'u_ROLAngularVelocityGradientMax', Laya.ShaderDataType.Vector4, 4);
            uniformMap.addShaderUniformArray(ShuriKenParticle3DShaderDeclaration.ROLANGULARVELOCITYGRADIENTXMAX, 'u_ROLAngularVelocityGradientMaxX', Laya.ShaderDataType.Vector4, 4);
            uniformMap.addShaderUniformArray(ShuriKenParticle3DShaderDeclaration.ROLANGULARVELOCITYGRADIENTYMAX, 'u_ROLAngularVelocityGradientMaxY', Laya.ShaderDataType.Vector4, 4);
            uniformMap.addShaderUniformArray(ShuriKenParticle3DShaderDeclaration.ROLANGULARVELOCITYGRADIENTZMAX, 'u_ROLAngularVelocityGradientMaxZ', Laya.ShaderDataType.Vector4, 4);
            uniformMap.addShaderUniform(ShuriKenParticle3DShaderDeclaration.TEXTURESHEETANIMATIONCYCLES, 'u_TSACycles', Laya.ShaderDataType.Float);
            uniformMap.addShaderUniform(ShuriKenParticle3DShaderDeclaration.TEXTURESHEETANIMATIONSUBUVLENGTH, 'u_TSASubUVLength', Laya.ShaderDataType.Vector2);
            uniformMap.addShaderUniformArray(ShuriKenParticle3DShaderDeclaration.TEXTURESHEETANIMATIONGRADIENTUVS, 'u_TSAGradientUVs', Laya.ShaderDataType.Vector4, 4);
            uniformMap.addShaderUniformArray(ShuriKenParticle3DShaderDeclaration.TEXTURESHEETANIMATIONGRADIENTMAXUVS, 'u_TSAMaxGradientUVs', Laya.ShaderDataType.Vector4, 4);
            uniformMap.addShaderUniform(ShuriKenParticle3DShaderDeclaration.DRAG, 'u_DragConstanct', Laya.ShaderDataType.Vector2);
            uniformMap.addShaderUniform(ShuriKenParticle3DShaderDeclaration.PIVOT, 'u_Pivot', Laya.ShaderDataType.Vector3);
        }
    }
    ShuriKenParticle3DShaderDeclaration.mulShaderDefineMode = true;

    class ShurikenParticleData {
        constructor() {
        }
        static _getStartLifetimeFromGradient(startLifeTimeGradient, emissionTime) {
            for (var i = 1, n = startLifeTimeGradient.gradientCount; i < n; i++) {
                var key = startLifeTimeGradient.getKeyByIndex(i);
                if (key >= emissionTime) {
                    var lastKey = startLifeTimeGradient.getKeyByIndex(i - 1);
                    var age = (emissionTime - lastKey) / (key - lastKey);
                    return Laya.MathUtil.lerp(startLifeTimeGradient.getValueByIndex(i - 1), startLifeTimeGradient.getValueByIndex(i), age);
                }
            }
            throw new Error("ShurikenParticleData: can't get value foam startLifeTimeGradient.");
        }
        static _randomInvertRoationArray(rotatonE, outE, randomizeRotationDirection, rand, randomSeeds) {
            var randDic;
            if (rand) {
                rand.seed = randomSeeds[6];
                randDic = rand.getFloat();
                randomSeeds[6] = rand.seed;
            }
            else {
                randDic = Math.random();
            }
            if (randDic < randomizeRotationDirection) {
                outE.x = -rotatonE.x;
                outE.y = -rotatonE.y;
                outE.z = -rotatonE.z;
            }
            else {
                outE.x = rotatonE.x;
                outE.y = rotatonE.y;
                outE.z = rotatonE.z;
            }
        }
        static _randomInvertRoation(rotaton, randomizeRotationDirection, rand, randomSeeds) {
            var randDic;
            if (rand) {
                rand.seed = randomSeeds[6];
                randDic = rand.getFloat();
                randomSeeds[6] = rand.seed;
            }
            else {
                randDic = Math.random();
            }
            if (randDic < randomizeRotationDirection)
                rotaton = -rotaton;
            return rotaton;
        }
        static create(particleSystem, particleRender) {
            var autoRandomSeed = particleSystem.autoRandomSeed;
            var rand = particleSystem._rand;
            var randomSeeds = particleSystem._randomSeeds;
            const duration = particleSystem.duration;
            const normalizedTime = duration > 0 ? (particleSystem.emissionTime % duration) / duration : 0;
            switch (particleSystem.startColorType) {
                case 0:
                    var constantStartColor = particleSystem.startColorConstant;
                    ShurikenParticleData.startColor.x = constantStartColor.x;
                    ShurikenParticleData.startColor.y = constantStartColor.y;
                    ShurikenParticleData.startColor.z = constantStartColor.z;
                    ShurikenParticleData.startColor.w = constantStartColor.w;
                    break;
                case 1:
                    particleSystem.startColorGradient.evaluateColorRGB(normalizedTime, tempColor);
                    ShurikenParticleData.startColor.x = tempColor.r;
                    ShurikenParticleData.startColor.y = tempColor.g;
                    ShurikenParticleData.startColor.z = tempColor.b;
                    ShurikenParticleData.startColor.w = tempColor.a;
                    break;
                case 2:
                    if (autoRandomSeed) {
                        Laya.Vector4.lerp(particleSystem.startColorConstantMin, particleSystem.startColorConstantMax, Math.random(), ShurikenParticleData.startColor);
                    }
                    else {
                        rand.seed = randomSeeds[3];
                        Laya.Vector4.lerp(particleSystem.startColorConstantMin, particleSystem.startColorConstantMax, rand.getFloat(), ShurikenParticleData.startColor);
                        randomSeeds[3] = rand.seed;
                    }
                    break;
                case 3: {
                    particleSystem.startColorGradientMin.evaluateColorRGB(normalizedTime, tempColor);
                    const colorMin = tempVector4;
                    colorMin.x = tempColor.r;
                    colorMin.y = tempColor.g;
                    colorMin.z = tempColor.b;
                    colorMin.w = tempColor.a;
                    particleSystem.startColorGradientMax.evaluateColorRGB(normalizedTime, tempColor);
                    const colorMax = tempVector41;
                    colorMax.x = tempColor.r;
                    colorMax.y = tempColor.g;
                    colorMax.z = tempColor.b;
                    colorMax.w = tempColor.a;
                    if (autoRandomSeed) {
                        Laya.Vector4.lerp(colorMin, colorMax, Math.random(), ShurikenParticleData.startColor);
                    }
                    else {
                        rand.seed = randomSeeds[3];
                        const lerp = rand.getFloat();
                        randomSeeds[3] = rand.seed;
                        Laya.Vector4.lerp(colorMin, colorMax, lerp, ShurikenParticleData.startColor);
                    }
                    break;
                }
            }
            var colorOverLifetime = particleSystem.colorOverLifetime;
            if (colorOverLifetime && colorOverLifetime.enable) {
                var color = colorOverLifetime.color;
                switch (color.type) {
                    case 0:
                        ShurikenParticleData.startColor.x = ShurikenParticleData.startColor.x * color.constant.x;
                        ShurikenParticleData.startColor.y = ShurikenParticleData.startColor.y * color.constant.y;
                        ShurikenParticleData.startColor.z = ShurikenParticleData.startColor.z * color.constant.z;
                        ShurikenParticleData.startColor.w = ShurikenParticleData.startColor.w * color.constant.w;
                        break;
                    case 2:
                        var colorRandom;
                        if (autoRandomSeed) {
                            colorRandom = Math.random();
                        }
                        else {
                            rand.seed = randomSeeds[10];
                            colorRandom = rand.getFloat();
                            randomSeeds[10] = rand.seed;
                        }
                        var minConstantColor = color.constantMin;
                        var maxConstantColor = color.constantMax;
                        ShurikenParticleData.startColor.x = ShurikenParticleData.startColor.x * Laya.MathUtil.lerp(minConstantColor.x, maxConstantColor.x, colorRandom);
                        ShurikenParticleData.startColor.y = ShurikenParticleData.startColor.y * Laya.MathUtil.lerp(minConstantColor.y, maxConstantColor.y, colorRandom);
                        ShurikenParticleData.startColor.z = ShurikenParticleData.startColor.z * Laya.MathUtil.lerp(minConstantColor.z, maxConstantColor.z, colorRandom);
                        ShurikenParticleData.startColor.w = ShurikenParticleData.startColor.w * Laya.MathUtil.lerp(minConstantColor.w, maxConstantColor.w, colorRandom);
                        break;
                }
            }
            var particleSize = ShurikenParticleData.startSize;
            switch (particleSystem.startSizeType) {
                case 0:
                    if (particleSystem.threeDStartSize) {
                        var startSizeConstantSeparate = particleSystem.startSizeConstantSeparate;
                        particleSize[0] = startSizeConstantSeparate.x;
                        particleSize[1] = startSizeConstantSeparate.y;
                        particleSize[2] = startSizeConstantSeparate.z;
                    }
                    else {
                        particleSize[0] = particleSize[1] = particleSize[2] = particleSystem.startSizeConstant;
                    }
                    break;
                case 2:
                    if (particleSystem.threeDStartSize) {
                        var startSizeConstantMinSeparate = particleSystem.startSizeConstantMinSeparate;
                        var startSizeConstantMaxSeparate = particleSystem.startSizeConstantMaxSeparate;
                        if (autoRandomSeed) {
                            particleSize[0] = Laya.MathUtil.lerp(startSizeConstantMinSeparate.x, startSizeConstantMaxSeparate.x, Math.random());
                            particleSize[1] = Laya.MathUtil.lerp(startSizeConstantMinSeparate.y, startSizeConstantMaxSeparate.y, Math.random());
                            particleSize[2] = Laya.MathUtil.lerp(startSizeConstantMinSeparate.z, startSizeConstantMaxSeparate.z, Math.random());
                        }
                        else {
                            rand.seed = randomSeeds[4];
                            particleSize[0] = Laya.MathUtil.lerp(startSizeConstantMinSeparate.x, startSizeConstantMaxSeparate.x, rand.getFloat());
                            particleSize[1] = Laya.MathUtil.lerp(startSizeConstantMinSeparate.y, startSizeConstantMaxSeparate.y, rand.getFloat());
                            particleSize[2] = Laya.MathUtil.lerp(startSizeConstantMinSeparate.z, startSizeConstantMaxSeparate.z, rand.getFloat());
                            randomSeeds[4] = rand.seed;
                        }
                    }
                    else {
                        if (autoRandomSeed) {
                            particleSize[0] = particleSize[1] = particleSize[2] = Laya.MathUtil.lerp(particleSystem.startSizeConstantMin, particleSystem.startSizeConstantMax, Math.random());
                        }
                        else {
                            rand.seed = randomSeeds[4];
                            particleSize[0] = particleSize[1] = particleSize[2] = Laya.MathUtil.lerp(particleSystem.startSizeConstantMin, particleSystem.startSizeConstantMax, rand.getFloat());
                            randomSeeds[4] = rand.seed;
                        }
                    }
                    break;
            }
            var sizeOverLifetime = particleSystem.sizeOverLifetime;
            if (sizeOverLifetime && sizeOverLifetime.enable && sizeOverLifetime.size.type === 1) {
                var size = sizeOverLifetime.size;
                if (size.separateAxes) {
                    if (autoRandomSeed) {
                        particleSize[0] = particleSize[0] * Laya.MathUtil.lerp(size.constantMinSeparate.x, size.constantMaxSeparate.x, Math.random());
                        particleSize[1] = particleSize[1] * Laya.MathUtil.lerp(size.constantMinSeparate.y, size.constantMaxSeparate.y, Math.random());
                        particleSize[2] = particleSize[2] * Laya.MathUtil.lerp(size.constantMinSeparate.z, size.constantMaxSeparate.z, Math.random());
                    }
                    else {
                        rand.seed = randomSeeds[11];
                        particleSize[0] = particleSize[0] * Laya.MathUtil.lerp(size.constantMinSeparate.x, size.constantMaxSeparate.x, rand.getFloat());
                        particleSize[1] = particleSize[1] * Laya.MathUtil.lerp(size.constantMinSeparate.y, size.constantMaxSeparate.y, rand.getFloat());
                        particleSize[2] = particleSize[2] * Laya.MathUtil.lerp(size.constantMinSeparate.z, size.constantMaxSeparate.z, rand.getFloat());
                        randomSeeds[11] = rand.seed;
                    }
                }
                else {
                    var randomSize;
                    if (autoRandomSeed) {
                        randomSize = Laya.MathUtil.lerp(size.constantMin, size.constantMax, Math.random());
                    }
                    else {
                        rand.seed = randomSeeds[11];
                        randomSize = Laya.MathUtil.lerp(size.constantMin, size.constantMax, rand.getFloat());
                        randomSeeds[11] = rand.seed;
                    }
                    particleSize[0] = particleSize[0] * randomSize;
                    particleSize[1] = particleSize[1] * randomSize;
                    particleSize[2] = particleSize[2] * randomSize;
                }
            }
            var renderMode = particleRender.renderMode;
            if (renderMode !== 1) {
                switch (particleSystem.startRotationType) {
                    case 0:
                        if (particleSystem.threeDStartRotation) {
                            var startRotationConstantSeparate = particleSystem.startRotationConstantSeparate;
                            var randomRotationE = _tempVector30$1;
                            ShurikenParticleData._randomInvertRoationArray(startRotationConstantSeparate, randomRotationE, particleSystem.randomizeRotationDirection, autoRandomSeed ? null : rand, randomSeeds);
                            ShurikenParticleData.startRotation[0] = randomRotationE.x;
                            ShurikenParticleData.startRotation[1] = randomRotationE.y;
                            if (renderMode !== 4)
                                ShurikenParticleData.startRotation[2] = -randomRotationE.z;
                            else
                                ShurikenParticleData.startRotation[2] = randomRotationE.z;
                        }
                        else {
                            ShurikenParticleData.startRotation[0] = ShurikenParticleData._randomInvertRoation(particleSystem.startRotationConstant, particleSystem.randomizeRotationDirection, autoRandomSeed ? null : rand, randomSeeds);
                            ShurikenParticleData.startRotation[1] = 0;
                            ShurikenParticleData.startRotation[2] = 0;
                        }
                        break;
                    case 2:
                        if (particleSystem.threeDStartRotation) {
                            var startRotationConstantMinSeparate = particleSystem.startRotationConstantMinSeparate;
                            var startRotationConstantMaxSeparate = particleSystem.startRotationConstantMaxSeparate;
                            var lerpRoationE = _tempVector30$1;
                            if (autoRandomSeed) {
                                lerpRoationE.x = Laya.MathUtil.lerp(startRotationConstantMinSeparate.x, startRotationConstantMaxSeparate.x, Math.random());
                                lerpRoationE.y = Laya.MathUtil.lerp(startRotationConstantMinSeparate.y, startRotationConstantMaxSeparate.y, Math.random());
                                lerpRoationE.z = Laya.MathUtil.lerp(startRotationConstantMinSeparate.z, startRotationConstantMaxSeparate.z, Math.random());
                            }
                            else {
                                rand.seed = randomSeeds[5];
                                lerpRoationE.x = Laya.MathUtil.lerp(startRotationConstantMinSeparate.x, startRotationConstantMaxSeparate.x, rand.getFloat());
                                lerpRoationE.y = Laya.MathUtil.lerp(startRotationConstantMinSeparate.y, startRotationConstantMaxSeparate.y, rand.getFloat());
                                lerpRoationE.z = Laya.MathUtil.lerp(startRotationConstantMinSeparate.z, startRotationConstantMaxSeparate.z, rand.getFloat());
                                randomSeeds[5] = rand.seed;
                            }
                            ShurikenParticleData._randomInvertRoationArray(lerpRoationE, lerpRoationE, particleSystem.randomizeRotationDirection, autoRandomSeed ? null : rand, randomSeeds);
                            ShurikenParticleData.startRotation[0] = lerpRoationE.x;
                            ShurikenParticleData.startRotation[1] = lerpRoationE.y;
                            if (renderMode !== 4)
                                ShurikenParticleData.startRotation[2] = -lerpRoationE.z;
                            else
                                ShurikenParticleData.startRotation[2] = lerpRoationE.z;
                        }
                        else {
                            if (autoRandomSeed) {
                                ShurikenParticleData.startRotation[0] = ShurikenParticleData._randomInvertRoation(Laya.MathUtil.lerp(particleSystem.startRotationConstantMin, particleSystem.startRotationConstantMax, Math.random()), particleSystem.randomizeRotationDirection, autoRandomSeed ? null : rand, randomSeeds);
                            }
                            else {
                                rand.seed = randomSeeds[5];
                                ShurikenParticleData.startRotation[0] = ShurikenParticleData._randomInvertRoation(Laya.MathUtil.lerp(particleSystem.startRotationConstantMin, particleSystem.startRotationConstantMax, rand.getFloat()), particleSystem.randomizeRotationDirection, autoRandomSeed ? null : rand, randomSeeds);
                                randomSeeds[5] = rand.seed;
                            }
                        }
                        break;
                }
            }
            switch (particleSystem.startLifetimeType) {
                case 0:
                    ShurikenParticleData.startLifeTime = particleSystem.startLifetimeConstant;
                    break;
                case 1:
                    ShurikenParticleData.startLifeTime = ShurikenParticleData._getStartLifetimeFromGradient(particleSystem.startLifeTimeGradient, particleSystem.emissionTime);
                    break;
                case 2:
                    if (autoRandomSeed) {
                        ShurikenParticleData.startLifeTime = Laya.MathUtil.lerp(particleSystem.startLifetimeConstantMin, particleSystem.startLifetimeConstantMax, Math.random());
                    }
                    else {
                        rand.seed = randomSeeds[7];
                        ShurikenParticleData.startLifeTime = Laya.MathUtil.lerp(particleSystem.startLifetimeConstantMin, particleSystem.startLifetimeConstantMax, rand.getFloat());
                        randomSeeds[7] = rand.seed;
                    }
                    break;
                case 3:
                    var emissionTime = particleSystem.emissionTime;
                    if (autoRandomSeed) {
                        ShurikenParticleData.startLifeTime = Laya.MathUtil.lerp(ShurikenParticleData._getStartLifetimeFromGradient(particleSystem.startLifeTimeGradientMin, emissionTime), ShurikenParticleData._getStartLifetimeFromGradient(particleSystem.startLifeTimeGradientMax, emissionTime), Math.random());
                    }
                    else {
                        rand.seed = randomSeeds[7];
                        ShurikenParticleData.startLifeTime = Laya.MathUtil.lerp(ShurikenParticleData._getStartLifetimeFromGradient(particleSystem.startLifeTimeGradientMin, emissionTime), ShurikenParticleData._getStartLifetimeFromGradient(particleSystem.startLifeTimeGradientMax, emissionTime), rand.getFloat());
                        randomSeeds[7] = rand.seed;
                    }
                    break;
            }
            var textureSheetAnimation = particleSystem.textureSheetAnimation;
            var enableSheetAnimation = textureSheetAnimation && textureSheetAnimation.enable;
            if (enableSheetAnimation) {
                var title = textureSheetAnimation.tiles;
                var titleX = title.x, titleY = title.y;
                var subU = 1.0 / titleX, subV = 1.0 / titleY;
                var startFrameCount;
                var startFrame = textureSheetAnimation.startFrame;
                switch (startFrame.type) {
                    case 0:
                        startFrameCount = startFrame.constant;
                        break;
                    case 1:
                        if (autoRandomSeed) {
                            startFrameCount = Laya.MathUtil.lerp(startFrame.constantMin, startFrame.constantMax, Math.random());
                        }
                        else {
                            rand.seed = randomSeeds[14];
                            startFrameCount = Laya.MathUtil.lerp(startFrame.constantMin, startFrame.constantMax, rand.getFloat());
                            randomSeeds[14] = rand.seed;
                        }
                        break;
                }
                var frame = textureSheetAnimation.frame;
                var cycles = textureSheetAnimation.cycles;
                switch (frame.type) {
                    case 0:
                        startFrameCount += frame.constant * cycles;
                        break;
                    case 2:
                        if (autoRandomSeed) {
                            startFrameCount += Laya.MathUtil.lerp(frame.constantMin, frame.constantMax, Math.random()) * cycles;
                        }
                        else {
                            rand.seed = randomSeeds[15];
                            startFrameCount += Laya.MathUtil.lerp(frame.constantMin, frame.constantMax, rand.getFloat()) * cycles;
                            randomSeeds[15] = rand.seed;
                        }
                        break;
                }
                var startRow = 0;
                switch (textureSheetAnimation.type) {
                    case 0:
                        startRow = Math.floor(startFrameCount / titleX);
                        break;
                    case 1:
                        if (textureSheetAnimation.randomRow) {
                            if (autoRandomSeed) {
                                startRow = Math.floor(Math.random() * titleY);
                            }
                            else {
                                rand.seed = randomSeeds[13];
                                startRow = Math.floor(rand.getFloat() * titleY);
                                randomSeeds[13] = rand.seed;
                            }
                        }
                        else {
                            startRow = textureSheetAnimation.rowIndex;
                        }
                        break;
                }
                var startCol = Math.floor(startFrameCount % titleX);
                ShurikenParticleData.startUVInfo = ShurikenParticleData.startUVInfo;
                ShurikenParticleData.startUVInfo[0] = subU;
                ShurikenParticleData.startUVInfo[1] = subV;
                ShurikenParticleData.startUVInfo[2] = startCol * subU;
                ShurikenParticleData.startUVInfo[3] = startRow * subV;
            }
            else {
                ShurikenParticleData.startUVInfo = ShurikenParticleData.startUVInfo;
                ShurikenParticleData.startUVInfo[0] = 1.0;
                ShurikenParticleData.startUVInfo[1] = 1.0;
                ShurikenParticleData.startUVInfo[2] = 0.0;
                ShurikenParticleData.startUVInfo[3] = 0.0;
            }
        }
    }
    ShurikenParticleData.startColor = new Laya.Vector4();
    ShurikenParticleData.startSize = new Float32Array(3);
    ShurikenParticleData.startRotation = new Float32Array(3);
    ShurikenParticleData.startUVInfo = new Float32Array(4);
    const _tempVector30$1 = new Laya.Vector3();
    const tempColor = new Laya.Color();
    const tempVector4 = new Laya.Vector4();
    const tempVector41 = new Laya.Vector4();

    class VertexShurikenParticleBillboard extends VertexShuriKenParticle {
        static get vertexDeclaration() {
            return VertexShurikenParticleBillboard._vertexDeclaration;
        }
        static get vertexInstanceMeshDeclaration() {
            return VertexShurikenParticleBillboard._vertexInstanceMeshDeclaration;
        }
        static get vertexInstanceParticleDeclaration() {
            return VertexShurikenParticleBillboard._vertexInstanceParticleDeclaration;
        }
        static get billboardVertexArray() {
            return VertexShurikenParticleBillboard._billboardVertexArray;
        }
        static get billboardIndexArray() {
            return VertexShurikenParticleBillboard._billboardIndexArray;
        }
        static set billboardIndexArray(value) {
            VertexShurikenParticleBillboard._billboardIndexArray = value;
        }
        static __init__() {
            VertexShurikenParticleBillboard._vertexDeclaration = new Laya.VertexDeclaration(168, [
                new Laya.VertexElement(0, Laya.VertexElementFormat.Vector4, VertexShuriKenParticle.PARTICLE_CORNERTEXTURECOORDINATE0),
                new Laya.VertexElement(16, Laya.VertexElementFormat.Vector4, VertexShuriKenParticle.PARTICLE_SHAPEPOSITIONSTARTLIFETIME),
                new Laya.VertexElement(32, Laya.VertexElementFormat.Vector4, VertexShuriKenParticle.PARTICLE_DIRECTIONTIME),
                new Laya.VertexElement(48, Laya.VertexElementFormat.Vector4, VertexShuriKenParticle.PARTICLE_STARTCOLOR0),
                new Laya.VertexElement(64, Laya.VertexElementFormat.Vector3, VertexShuriKenParticle.PARTICLE_STARTSIZE),
                new Laya.VertexElement(76, Laya.VertexElementFormat.Vector3, VertexShuriKenParticle.PARTICLE_STARTROTATION),
                new Laya.VertexElement(88, Laya.VertexElementFormat.Single, VertexShuriKenParticle.PARTICLE_STARTSPEED),
                new Laya.VertexElement(92, Laya.VertexElementFormat.Vector4, VertexShuriKenParticle.PARTICLE_RANDOM0),
                new Laya.VertexElement(108, Laya.VertexElementFormat.Vector4, VertexShuriKenParticle.PARTICLE_RANDOM1),
                new Laya.VertexElement(124, Laya.VertexElementFormat.Vector3, VertexShuriKenParticle.PARTICLE_SIMULATIONWORLDPOSTION),
                new Laya.VertexElement(136, Laya.VertexElementFormat.Vector4, VertexShuriKenParticle.PARTICLE_SIMULATIONWORLDROTATION),
                new Laya.VertexElement(152, Laya.VertexElementFormat.Vector4, VertexShuriKenParticle.PARTICLE_SIMULATIONUV)
            ]);
            VertexShurikenParticleBillboard._vertexInstanceMeshDeclaration = new Laya.VertexDeclaration(16, [
                new Laya.VertexElement(0, Laya.VertexElementFormat.Vector4, VertexShuriKenParticle.PARTICLE_CORNERTEXTURECOORDINATE0)
            ]);
            VertexShurikenParticleBillboard._vertexInstanceParticleDeclaration = new Laya.VertexDeclaration(152, [
                new Laya.VertexElement(0, Laya.VertexElementFormat.Vector4, VertexShuriKenParticle.PARTICLE_SHAPEPOSITIONSTARTLIFETIME),
                new Laya.VertexElement(16, Laya.VertexElementFormat.Vector4, VertexShuriKenParticle.PARTICLE_DIRECTIONTIME),
                new Laya.VertexElement(32, Laya.VertexElementFormat.Vector4, VertexShuriKenParticle.PARTICLE_STARTCOLOR0),
                new Laya.VertexElement(48, Laya.VertexElementFormat.Vector3, VertexShuriKenParticle.PARTICLE_STARTSIZE),
                new Laya.VertexElement(60, Laya.VertexElementFormat.Vector3, VertexShuriKenParticle.PARTICLE_STARTROTATION),
                new Laya.VertexElement(72, Laya.VertexElementFormat.Single, VertexShuriKenParticle.PARTICLE_STARTSPEED),
                new Laya.VertexElement(76, Laya.VertexElementFormat.Vector4, VertexShuriKenParticle.PARTICLE_RANDOM0),
                new Laya.VertexElement(92, Laya.VertexElementFormat.Vector4, VertexShuriKenParticle.PARTICLE_RANDOM1),
                new Laya.VertexElement(108, Laya.VertexElementFormat.Vector3, VertexShuriKenParticle.PARTICLE_SIMULATIONWORLDPOSTION),
                new Laya.VertexElement(120, Laya.VertexElementFormat.Vector4, VertexShuriKenParticle.PARTICLE_SIMULATIONWORLDROTATION),
                new Laya.VertexElement(136, Laya.VertexElementFormat.Vector4, VertexShuriKenParticle.PARTICLE_SIMULATIONUV)
            ]);
            VertexShurikenParticleBillboard._billboardIndexArray = new Uint16Array([
                0, 2, 1, 0, 3, 2
            ]);
            VertexShurikenParticleBillboard._billboardVertexArray = new Float32Array([
                -0.5, -0.5, 0, 1,
                0.5, -0.5, 1, 1,
                0.5, 0.5, 1, 0,
                -0.5, 0.5, 0, 0
            ]);
        }
        get cornerTextureCoordinate() {
            return this._cornerTextureCoordinate;
        }
        get positionStartLifeTime() {
            return this._positionStartLifeTime;
        }
        get velocity() {
            return this._velocity;
        }
        get startColor() {
            return this._startColor;
        }
        get startSize() {
            return this._startSize;
        }
        get startRotation0() {
            return this._startRotation0;
        }
        get startRotation1() {
            return this._startRotation1;
        }
        get startRotation2() {
            return this._startRotation2;
        }
        get startLifeTime() {
            return this._startLifeTime;
        }
        get time() {
            return this._time;
        }
        get startSpeed() {
            return this._startSpeed;
        }
        get random0() {
            return this._randoms0;
        }
        get random1() {
            return this._randoms1;
        }
        get simulationWorldPostion() {
            return this._simulationWorldPostion;
        }
        constructor(cornerTextureCoordinate, positionStartLifeTime, velocity, startColor, startSize, startRotation0, startRotation1, startRotation2, ageAddScale, time, startSpeed, randoms0, randoms1, simulationWorldPostion) {
            super();
            this._cornerTextureCoordinate = cornerTextureCoordinate;
            this._positionStartLifeTime = positionStartLifeTime;
            this._velocity = velocity;
            this._startColor = startColor;
            this._startSize = startSize;
            this._startRotation0 = startRotation0;
            this._startRotation1 = startRotation1;
            this._startRotation2 = startRotation2;
            this._startLifeTime = ageAddScale;
            this._time = time;
            this._startSpeed = startSpeed;
            this._randoms0 = randoms0;
            this._randoms1 = randoms1;
            this._simulationWorldPostion = simulationWorldPostion;
        }
    }

    class VertexShurikenParticleMesh extends VertexShuriKenParticle {
        static __init__() {
            VertexShurikenParticleMesh._vertexDeclaration = new Laya.VertexDeclaration(188, [new Laya.VertexElement(0, Laya.VertexElementFormat.Vector3, VertexShuriKenParticle.PARTICLE_POSITION0),
                new Laya.VertexElement(12, Laya.VertexElementFormat.Vector4, VertexShuriKenParticle.PARTICLE_COLOR0),
                new Laya.VertexElement(28, Laya.VertexElementFormat.Vector2, VertexShuriKenParticle.PARTICLE_TEXTURECOORDINATE0),
                new Laya.VertexElement(36, Laya.VertexElementFormat.Vector4, VertexShuriKenParticle.PARTICLE_SHAPEPOSITIONSTARTLIFETIME),
                new Laya.VertexElement(52, Laya.VertexElementFormat.Vector4, VertexShuriKenParticle.PARTICLE_DIRECTIONTIME),
                new Laya.VertexElement(68, Laya.VertexElementFormat.Vector4, VertexShuriKenParticle.PARTICLE_STARTCOLOR0),
                new Laya.VertexElement(84, Laya.VertexElementFormat.Vector3, VertexShuriKenParticle.PARTICLE_STARTSIZE),
                new Laya.VertexElement(96, Laya.VertexElementFormat.Vector3, VertexShuriKenParticle.PARTICLE_STARTROTATION),
                new Laya.VertexElement(108, Laya.VertexElementFormat.Single, VertexShuriKenParticle.PARTICLE_STARTSPEED),
                new Laya.VertexElement(112, Laya.VertexElementFormat.Vector4, VertexShuriKenParticle.PARTICLE_RANDOM0),
                new Laya.VertexElement(128, Laya.VertexElementFormat.Vector4, VertexShuriKenParticle.PARTICLE_RANDOM1),
                new Laya.VertexElement(144, Laya.VertexElementFormat.Vector3, VertexShuriKenParticle.PARTICLE_SIMULATIONWORLDPOSTION),
                new Laya.VertexElement(156, Laya.VertexElementFormat.Vector4, VertexShuriKenParticle.PARTICLE_SIMULATIONWORLDROTATION),
                new Laya.VertexElement(172, Laya.VertexElementFormat.Vector4, VertexShuriKenParticle.PARTICLE_SIMULATIONUV)]);
            VertexShurikenParticleMesh._vertexInstanceMeshDeclaration = new Laya.VertexDeclaration(36, [
                new Laya.VertexElement(0, Laya.VertexElementFormat.Vector3, VertexShuriKenParticle.PARTICLE_POSITION0),
                new Laya.VertexElement(12, Laya.VertexElementFormat.Vector4, VertexShuriKenParticle.PARTICLE_COLOR0),
                new Laya.VertexElement(28, Laya.VertexElementFormat.Vector2, VertexShuriKenParticle.PARTICLE_TEXTURECOORDINATE0)
            ]);
            VertexShurikenParticleMesh._vertexInstanceParticleDeclaration = new Laya.VertexDeclaration(152, [
                new Laya.VertexElement(0, Laya.VertexElementFormat.Vector4, VertexShuriKenParticle.PARTICLE_SHAPEPOSITIONSTARTLIFETIME),
                new Laya.VertexElement(16, Laya.VertexElementFormat.Vector4, VertexShuriKenParticle.PARTICLE_DIRECTIONTIME),
                new Laya.VertexElement(32, Laya.VertexElementFormat.Vector4, VertexShuriKenParticle.PARTICLE_STARTCOLOR0),
                new Laya.VertexElement(48, Laya.VertexElementFormat.Vector3, VertexShuriKenParticle.PARTICLE_STARTSIZE),
                new Laya.VertexElement(60, Laya.VertexElementFormat.Vector3, VertexShuriKenParticle.PARTICLE_STARTROTATION),
                new Laya.VertexElement(72, Laya.VertexElementFormat.Single, VertexShuriKenParticle.PARTICLE_STARTSPEED),
                new Laya.VertexElement(76, Laya.VertexElementFormat.Vector4, VertexShuriKenParticle.PARTICLE_RANDOM0),
                new Laya.VertexElement(92, Laya.VertexElementFormat.Vector4, VertexShuriKenParticle.PARTICLE_RANDOM1),
                new Laya.VertexElement(108, Laya.VertexElementFormat.Vector3, VertexShuriKenParticle.PARTICLE_SIMULATIONWORLDPOSTION),
                new Laya.VertexElement(120, Laya.VertexElementFormat.Vector4, VertexShuriKenParticle.PARTICLE_SIMULATIONWORLDROTATION),
                new Laya.VertexElement(136, Laya.VertexElementFormat.Vector4, VertexShuriKenParticle.PARTICLE_SIMULATIONUV)
            ]);
        }
        static get vertexDeclaration() {
            return VertexShurikenParticleMesh._vertexDeclaration;
        }
        static get vertexInstanceMeshDeclaration() {
            return VertexShurikenParticleMesh._vertexInstanceMeshDeclaration;
        }
        static get vertexInstanceParticleDeclaration() {
            return VertexShurikenParticleMesh._vertexInstanceParticleDeclaration;
        }
        get cornerTextureCoordinate() {
            return this._cornerTextureCoordinate;
        }
        get position() {
            return this._positionStartLifeTime;
        }
        get velocity() {
            return this._velocity;
        }
        get startColor() {
            return this._startColor;
        }
        get startSize() {
            return this._startSize;
        }
        get startRotation0() {
            return this._startRotation0;
        }
        get startRotation1() {
            return this._startRotation1;
        }
        get startRotation2() {
            return this._startRotation2;
        }
        get startLifeTime() {
            return this._startLifeTime;
        }
        get time() {
            return this._time;
        }
        get startSpeed() {
            return this._startSpeed;
        }
        get random0() {
            return this._randoms0;
        }
        get random1() {
            return this._randoms1;
        }
        get simulationWorldPostion() {
            return this._simulationWorldPostion;
        }
        constructor(cornerTextureCoordinate, positionStartLifeTime, velocity, startColor, startSize, startRotation0, startRotation1, startRotation2, ageAddScale, time, startSpeed, randoms0, randoms1, simulationWorldPostion) {
            super();
            this._cornerTextureCoordinate = cornerTextureCoordinate;
            this._positionStartLifeTime = positionStartLifeTime;
            this._velocity = velocity;
            this._startColor = startColor;
            this._startSize = startSize;
            this._startRotation0 = startRotation0;
            this._startRotation1 = startRotation1;
            this._startRotation2 = startRotation2;
            this._startLifeTime = ageAddScale;
            this._time = time;
            this._startSpeed = startSpeed;
            this._randoms0 = randoms0;
            this._randoms1 = randoms1;
            this._simulationWorldPostion = simulationWorldPostion;
        }
    }

    const tempV3$1 = new Laya.Vector3();
    class ShurikenParticleSystem extends Laya.GeometryElement {
        get gradientKeyCount8() {
            return this._gradientKeyCount8;
        }
        set gradientKeyCount8(value) {
            if (this._gradientKeyCount8 !== value) {
                this._gradientKeyCount8 = value;
                var shaDat = this._ownerRender._baseRenderNode.shaderData;
                if (value) {
                    shaDat.addDefine(ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_GRADIENTKEYCOUNT_8);
                }
                else {
                    shaDat.removeDefine(ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_GRADIENTKEYCOUNT_8);
                }
            }
        }
        get maxParticles() {
            return this._bufferMaxParticles - 1;
        }
        set maxParticles(value) {
            var newMaxParticles = value + 1;
            if (newMaxParticles !== this._bufferMaxParticles) {
                this._bufferMaxParticles = newMaxParticles;
                this._initBufferDatas();
            }
            if (!Laya.SerializeUtil.isDeserializing)
                this._updateParticlesSimulationRestart(0);
        }
        get emission() {
            return this._emission;
        }
        get aliveParticleCount() {
            if (this._firstNewElement >= this._firstRetiredElement)
                return this._firstNewElement - this._firstRetiredElement;
            else
                return this._bufferMaxParticles - this._firstRetiredElement + this._firstNewElement;
        }
        get emissionTime() {
            return this._emissionTime > this.duration ? this.duration : this._emissionTime;
        }
        get shape() {
            return this._shape;
        }
        set shape(value) {
            if (this._shape !== value) {
                if (value && value.enable)
                    this._ownerRender._baseRenderNode.shaderData.addDefine(ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_SHAPE);
                else
                    this._ownerRender._baseRenderNode.shaderData.removeDefine(ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_SHAPE);
                this._shape = value;
            }
        }
        get isAlive() {
            if (this._isPlaying || this.aliveParticleCount > 0)
                return true;
            return false;
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
        get startLifetimeType() {
            return this._startLifetimeType;
        }
        set startLifetimeType(value) {
            var i, n;
            switch (this._startLifetimeType) {
                case 0:
                    this._maxStartLifetime = this._startLifetimeConstant;
                    break;
                case 1:
                    this._maxStartLifetime = -Number.MAX_VALUE;
                    var startLifeTimeGradient = startLifeTimeGradient;
                    for (i = 0, n = startLifeTimeGradient.gradientCount; i < n; i++)
                        this._maxStartLifetime = Math.max(this._maxStartLifetime, startLifeTimeGradient.getValueByIndex(i));
                    break;
                case 2:
                    this._maxStartLifetime = Math.max(this._startLifetimeConstantMin, this._startLifetimeConstantMax);
                    break;
                case 3:
                    this._maxStartLifetime = -Number.MAX_VALUE;
                    var startLifeTimeGradientMin = startLifeTimeGradientMin;
                    for (i = 0, n = startLifeTimeGradientMin.gradientCount; i < n; i++)
                        this._maxStartLifetime = Math.max(this._maxStartLifetime, startLifeTimeGradientMin.getValueByIndex(i));
                    var startLifeTimeGradientMax = startLifeTimeGradientMax;
                    for (i = 0, n = startLifeTimeGradientMax.gradientCount; i < n; i++)
                        this._maxStartLifetime = Math.max(this._maxStartLifetime, startLifeTimeGradientMax.getValueByIndex(i));
                    break;
            }
            this._startLifetimeType = value;
        }
        get startLifetimeConstant() {
            return this._startLifetimeConstant;
        }
        set startLifetimeConstant(value) {
            if (this._startLifetimeType === 0)
                this._maxStartLifetime = value;
            this._startLifetimeConstant = value;
        }
        get startLifeTimeGradient() {
            return this._startLifeTimeGradient;
        }
        set startLifeTimeGradient(value) {
            if (this._startLifetimeType === 1) {
                this._maxStartLifetime = -Number.MAX_VALUE;
                for (var i = 0, n = value.gradientCount; i < n; i++)
                    this._maxStartLifetime = Math.max(this._maxStartLifetime, value.getValueByIndex(i));
            }
            this._startLifeTimeGradient = value;
        }
        get startLifetimeConstantMin() {
            return this._startLifetimeConstantMin;
        }
        set startLifetimeConstantMin(value) {
            if (this._startLifetimeType === 2)
                this._maxStartLifetime = Math.max(value, this._startLifetimeConstantMax);
            this._startLifetimeConstantMin = value;
        }
        get startLifetimeConstantMax() {
            return this._startLifetimeConstantMax;
        }
        set startLifetimeConstantMax(value) {
            if (this._startLifetimeType === 2)
                this._maxStartLifetime = Math.max(this._startLifetimeConstantMin, value);
            this._startLifetimeConstantMax = value;
        }
        get startLifeTimeGradientMin() {
            return this._startLifeTimeGradientMin;
        }
        set startLifeTimeGradientMin(value) {
            if (this._startLifetimeType === 3) {
                var i, n;
                this._maxStartLifetime = -Number.MAX_VALUE;
                for (i = 0, n = value.gradientCount; i < n; i++)
                    this._maxStartLifetime = Math.max(this._maxStartLifetime, value.getValueByIndex(i));
                for (i = 0, n = this._startLifeTimeGradientMax.gradientCount; i < n; i++)
                    this._maxStartLifetime = Math.max(this._maxStartLifetime, this._startLifeTimeGradientMax.getValueByIndex(i));
            }
            this._startLifeTimeGradientMin = value;
        }
        get startLifeTimeGradientMax() {
            return this._startLifeTimeGradientMax;
        }
        set startLifeTimeGradientMax(value) {
            if (this._startLifetimeType === 3) {
                var i, n;
                this._maxStartLifetime = -Number.MAX_VALUE;
                for (i = 0, n = this._startLifeTimeGradientMin.gradientCount; i < n; i++)
                    this._maxStartLifetime = Math.max(this._maxStartLifetime, this._startLifeTimeGradientMin.getValueByIndex(i));
                for (i = 0, n = value.gradientCount; i < n; i++)
                    this._maxStartLifetime = Math.max(this._maxStartLifetime, value.getValueByIndex(i));
            }
            this._startLifeTimeGradientMax = value;
        }
        get velocityOverLifetime() {
            return this._velocityOverLifetime;
        }
        set velocityOverLifetime(value) {
            var shaDat = this._ownerRender._baseRenderNode.shaderData;
            if (this._mulDefMode) {
                shaDat.removeDefine(ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_VELOCITYOVERLIFETIMECONSTANT);
                shaDat.removeDefine(ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_VELOCITYOVERLIFETIMECURVE);
                shaDat.removeDefine(ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_VELOCITYOVERLIFETIMERANDOMCONSTANT);
            }
            shaDat.removeDefine(ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_VELOCITYOVERLIFETIMERANDOMCURVE);
            this._velocityOverLifetime = value;
            if (value) {
                var velocity = value.velocity;
                var velocityType = velocity.type;
                if (value.enable) {
                    if (!this._mulDefMode)
                        shaDat.addDefine(ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_VELOCITYOVERLIFETIMERANDOMCURVE);
                    switch (velocityType) {
                        case 0:
                            if (this._mulDefMode) {
                                shaDat.addDefine(ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_VELOCITYOVERLIFETIMECONSTANT);
                                shaDat.setVector3(ShuriKenParticle3DShaderDeclaration.VOLVELOCITYCONST, velocity.constant);
                            }
                            else {
                                velocity.gradientConstantX._formatData();
                                velocity.gradientConstantY._formatData();
                                velocity.gradientConstantZ._formatData();
                                shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.VOLVELOCITYGRADIENTX, velocity.gradientConstantX._elements);
                                shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.VOLVELOCITYGRADIENTY, velocity.gradientConstantY._elements);
                                shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.VOLVELOCITYGRADIENTZ, velocity.gradientConstantZ._elements);
                                shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.VOLVELOCITYGRADIENTXMAX, velocity.gradientConstantX._elements);
                                shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.VOLVELOCITYGRADIENTYMAX, velocity.gradientConstantY._elements);
                                shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.VOLVELOCITYGRADIENTZMAX, velocity.gradientConstantZ._elements);
                            }
                            break;
                        case 1:
                            velocity.gradientX._formatData();
                            velocity.gradientY._formatData();
                            velocity.gradientZ._formatData();
                            shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.VOLVELOCITYGRADIENTX, velocity.gradientX._elements);
                            shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.VOLVELOCITYGRADIENTY, velocity.gradientY._elements);
                            shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.VOLVELOCITYGRADIENTZ, velocity.gradientZ._elements);
                            if (this._mulDefMode) {
                                shaDat.addDefine(ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_VELOCITYOVERLIFETIMECURVE);
                            }
                            else {
                                shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.VOLVELOCITYGRADIENTXMAX, velocity.gradientX._elements);
                                shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.VOLVELOCITYGRADIENTZMAX, velocity.gradientZ._elements);
                                shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.VOLVELOCITYGRADIENTYMAX, velocity.gradientY._elements);
                            }
                            break;
                        case 2:
                            if (this._mulDefMode) {
                                shaDat.addDefine(ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_VELOCITYOVERLIFETIMERANDOMCONSTANT);
                                shaDat.setVector3(ShuriKenParticle3DShaderDeclaration.VOLVELOCITYCONST, velocity.constantMin);
                                shaDat.setVector3(ShuriKenParticle3DShaderDeclaration.VOLVELOCITYCONSTMAX, velocity.constantMax);
                            }
                            else {
                                velocity.gradientConstantXMin._formatData();
                                velocity.gradientConstantYMin._formatData();
                                velocity.gradientConstantZMin._formatData();
                                velocity.gradientConstantXMax._formatData();
                                velocity.gradientConstantYMax._formatData();
                                velocity.gradientConstantZMax._formatData();
                                shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.VOLVELOCITYGRADIENTX, velocity.gradientConstantXMin._elements);
                                shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.VOLVELOCITYGRADIENTY, velocity.gradientConstantYMin._elements);
                                shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.VOLVELOCITYGRADIENTZ, velocity.gradientConstantZMin._elements);
                                shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.VOLVELOCITYGRADIENTXMAX, velocity.gradientConstantXMax._elements);
                                shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.VOLVELOCITYGRADIENTYMAX, velocity.gradientConstantYMax._elements);
                                shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.VOLVELOCITYGRADIENTZMAX, velocity.gradientConstantZMax._elements);
                            }
                            break;
                        case 3:
                            velocity.gradientXMin._formatData();
                            velocity.gradientYMin._formatData();
                            velocity.gradientZMin._formatData();
                            velocity.gradientXMax._formatData();
                            velocity.gradientYMax._formatData();
                            velocity.gradientZMax._formatData();
                            if (this._mulDefMode)
                                shaDat.addDefine(ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_VELOCITYOVERLIFETIMERANDOMCURVE);
                            shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.VOLVELOCITYGRADIENTX, velocity.gradientXMin._elements);
                            shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.VOLVELOCITYGRADIENTY, velocity.gradientYMin._elements);
                            shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.VOLVELOCITYGRADIENTZ, velocity.gradientZMin._elements);
                            shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.VOLVELOCITYGRADIENTXMAX, velocity.gradientXMax._elements);
                            shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.VOLVELOCITYGRADIENTZMAX, velocity.gradientZMax._elements);
                            shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.VOLVELOCITYGRADIENTYMAX, velocity.gradientYMax._elements);
                            break;
                    }
                }
                shaDat.setInt(ShuriKenParticle3DShaderDeclaration.VOLSPACETYPE, value.space);
            }
        }
        get colorOverLifetime() {
            return this._colorOverLifetime;
        }
        set colorOverLifetime(value) {
            var shaDat = this._ownerRender._baseRenderNode.shaderData;
            if (this._mulDefMode)
                shaDat.removeDefine(ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_COLOROVERLIFETIME);
            shaDat.removeDefine(ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_RANDOMCOLOROVERLIFETIME);
            this._colorOverLifetime = value;
            if (value) {
                var color = value.color;
                if (value.enable) {
                    switch (color.type) {
                        case 1:
                            let gradientColor = color.gradient;
                            let alphaElements;
                            let rgbElements;
                            if (gradientColor.maxColorKeysCount > 4) {
                                shaDat.addDefine(ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_COLORKEYCOUNT_8);
                                alphaElements = gradientColor._getGPUAlphaData8();
                                rgbElements = gradientColor._getGPURGBData8();
                            }
                            else {
                                shaDat.removeDefine(ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_COLORKEYCOUNT_8);
                                alphaElements = gradientColor._getGPUAlphaData4();
                                rgbElements = gradientColor._getGPURGBData4();
                            }
                            shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.COLOROVERLIFEGRADIENTALPHAS, alphaElements);
                            shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.COLOROVERLIFEGRADIENTCOLORS, rgbElements);
                            let ranges = gradientColor._keyRanges;
                            ranges.setValue(1, 0, 1, 0);
                            for (let index = 0, n = Math.max(2, gradientColor.colorRGBKeysCount); index < n; index++) {
                                let colorKey = rgbElements[index * 4];
                                ranges.x = Math.min(ranges.x, colorKey);
                                ranges.y = Math.max(ranges.y, colorKey);
                            }
                            for (let index = 0, n = Math.max(2, gradientColor.colorAlphaKeysCount); index < n; index++) {
                                let alphaKey = alphaElements[index * 2];
                                ranges.z = Math.min(ranges.z, alphaKey);
                                ranges.w = Math.max(ranges.w, alphaKey);
                            }
                            shaDat.setVector(ShuriKenParticle3DShaderDeclaration.COLOROVERLIFEGRADIENTRANGES, ranges);
                            if (this._mulDefMode) {
                                shaDat.addDefine(ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_COLOROVERLIFETIME);
                            }
                            else {
                                shaDat.addDefine(ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_RANDOMCOLOROVERLIFETIME);
                                shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.MAXCOLOROVERLIFEGRADIENTALPHAS, alphaElements);
                                shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.MAXCOLOROVERLIFEGRADIENTCOLORS, rgbElements);
                                shaDat.setVector(ShuriKenParticle3DShaderDeclaration.MAXCOLOROVERLIFEGRADIENTRANGES, ranges);
                            }
                            break;
                        case 3:
                            shaDat.addDefine(ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_RANDOMCOLOROVERLIFETIME);
                            let minGradientColor = color.gradientMin;
                            let maxGradientColor = color.gradientMax;
                            let minalphaElements;
                            let minrgbElements;
                            let maxalphaElements;
                            let maxrgbElements;
                            let maxkeyCount = Math.max(minGradientColor.maxColorKeysCount, maxGradientColor.maxColorKeysCount);
                            if (maxkeyCount > 4) {
                                shaDat.addDefine(ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_COLORKEYCOUNT_8);
                                minalphaElements = minGradientColor._getGPUAlphaData8();
                                minrgbElements = minGradientColor._getGPURGBData8();
                                maxalphaElements = maxGradientColor._getGPUAlphaData8();
                                maxrgbElements = maxGradientColor._getGPURGBData8();
                            }
                            else {
                                shaDat.removeDefine(ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_COLORKEYCOUNT_8);
                                minalphaElements = minGradientColor._getGPUAlphaData4();
                                minrgbElements = minGradientColor._getGPURGBData4();
                                maxalphaElements = maxGradientColor._getGPUAlphaData4();
                                maxrgbElements = maxGradientColor._getGPURGBData4();
                            }
                            shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.COLOROVERLIFEGRADIENTALPHAS, minalphaElements);
                            shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.COLOROVERLIFEGRADIENTCOLORS, minrgbElements);
                            shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.MAXCOLOROVERLIFEGRADIENTALPHAS, maxalphaElements);
                            shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.MAXCOLOROVERLIFEGRADIENTCOLORS, maxrgbElements);
                            let minRanges = minGradientColor._keyRanges;
                            minRanges.setValue(1, 0, 1, 0);
                            for (let index = 0, n = Math.max(2, minGradientColor.colorRGBKeysCount); index < n; index++) {
                                let colorKey = minrgbElements[index * 4];
                                minRanges.x = Math.min(minRanges.x, colorKey);
                                minRanges.y = Math.max(minRanges.y, colorKey);
                            }
                            for (let index = 0, n = Math.max(2, minGradientColor.colorAlphaKeysCount); index < n; index++) {
                                let alphaKey = minalphaElements[index * 2];
                                minRanges.z = Math.min(minRanges.z, alphaKey);
                                minRanges.w = Math.max(minRanges.w, alphaKey);
                            }
                            shaDat.setVector(ShuriKenParticle3DShaderDeclaration.COLOROVERLIFEGRADIENTRANGES, minRanges);
                            let maxRanges = maxGradientColor._keyRanges;
                            maxRanges.setValue(1, 0, 1, 0);
                            for (let index = 0, n = Math.max(2, maxGradientColor.colorRGBKeysCount); index < n; index++) {
                                let colorKey = maxrgbElements[index * 4];
                                maxRanges.x = Math.min(maxRanges.x, colorKey);
                                maxRanges.y = Math.max(maxRanges.y, colorKey);
                            }
                            for (let index = 0, n = Math.max(2, maxGradientColor.colorAlphaKeysCount); index < n; index++) {
                                let alphaKey = maxalphaElements[index * 2];
                                maxRanges.z = Math.min(maxRanges.z, alphaKey);
                                maxRanges.w = Math.max(maxRanges.w, alphaKey);
                            }
                            shaDat.setVector(ShuriKenParticle3DShaderDeclaration.MAXCOLOROVERLIFEGRADIENTRANGES, maxRanges);
                            break;
                    }
                }
            }
        }
        get sizeOverLifetime() {
            return this._sizeOverLifetime;
        }
        set sizeOverLifetime(value) {
            var shaDat = this._ownerRender._baseRenderNode.shaderData;
            if (this._mulDefMode) {
                shaDat.removeDefine(ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_SIZEOVERLIFETIMECURVE);
                shaDat.removeDefine(ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_SIZEOVERLIFETIMECURVESEPERATE);
            }
            shaDat.removeDefine(ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_SIZEOVERLIFETIMERANDOMCURVES);
            shaDat.removeDefine(ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_SIZEOVERLIFETIMERANDOMCURVESSEPERATE);
            this._sizeOverLifetime = value;
            if (value) {
                var size = value.size;
                var sizeSeparate = size.separateAxes;
                var sizeType = size.type;
                if (value.enable) {
                    switch (sizeType) {
                        case 0:
                            if (sizeSeparate) {
                                size.gradientX._formatData();
                                size.gradientY._formatData();
                                size.gradientZ._formatData();
                                shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.SOLSIZEGRADIENTX, size.gradientX._elements);
                                shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.SOLSIZEGRADIENTY, size.gradientY._elements);
                                shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.SOLSizeGradientZ, size.gradientZ._elements);
                                if (this._mulDefMode) {
                                    shaDat.addDefine(ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_SIZEOVERLIFETIMECURVESEPERATE);
                                }
                                else {
                                    shaDat.addDefine(ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_SIZEOVERLIFETIMERANDOMCURVESSEPERATE);
                                    shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.SOLSIZEGRADIENTXMAX, size.gradientX._elements);
                                    shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.SOLSIZEGRADIENTYMAX, size.gradientY._elements);
                                    shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.SOLSizeGradientZMAX, size.gradientZ._elements);
                                }
                            }
                            else {
                                size.gradient._formatData();
                                shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.SOLSIZEGRADIENT, size.gradient._elements);
                                if (this._mulDefMode) {
                                    shaDat.addDefine(ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_SIZEOVERLIFETIMECURVE);
                                }
                                else {
                                    shaDat.addDefine(ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_SIZEOVERLIFETIMERANDOMCURVES);
                                    shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.SOLSizeGradientMax, size.gradient._elements);
                                }
                            }
                            break;
                        case 2:
                            if (sizeSeparate) {
                                shaDat.addDefine(ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_SIZEOVERLIFETIMERANDOMCURVESSEPERATE);
                                size.gradientXMin._formatData();
                                size.gradientXMax._formatData();
                                size.gradientYMin._formatData();
                                size.gradientYMax._formatData();
                                size.gradientZMin._formatData();
                                size.gradientZMax._formatData();
                                shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.SOLSIZEGRADIENTX, size.gradientXMin._elements);
                                shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.SOLSIZEGRADIENTXMAX, size.gradientXMax._elements);
                                shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.SOLSIZEGRADIENTY, size.gradientYMin._elements);
                                shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.SOLSIZEGRADIENTYMAX, size.gradientYMax._elements);
                                shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.SOLSizeGradientZ, size.gradientZMin._elements);
                                shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.SOLSizeGradientZMAX, size.gradientZMax._elements);
                            }
                            else {
                                shaDat.addDefine(ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_SIZEOVERLIFETIMERANDOMCURVES);
                                size.gradientMin._formatData();
                                size.gradientMax._formatData();
                                shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.SOLSIZEGRADIENT, size.gradientMin._elements);
                                shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.SOLSizeGradientMax, size.gradientMax._elements);
                            }
                            break;
                    }
                }
            }
        }
        get rotationOverLifetime() {
            return this._rotationOverLifetime;
        }
        set rotationOverLifetime(value) {
            var shaDat = this._ownerRender._baseRenderNode.shaderData;
            shaDat.removeDefine(ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_ROTATIONOVERLIFETIME);
            shaDat.removeDefine(ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_ROTATIONOVERLIFETIMESEPERATE);
            if (this._mulDefMode) {
                shaDat.removeDefine(ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_ROTATIONOVERLIFETIMECONSTANT);
                shaDat.removeDefine(ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_ROTATIONOVERLIFETIMECURVE);
                shaDat.removeDefine(ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_ROTATIONOVERLIFETIMERANDOMCONSTANTS);
                shaDat.removeDefine(ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_ROTATIONOVERLIFETIMERANDOMCURVES);
            }
            this._rotationOverLifetime = value;
            if (value) {
                var rotation = value.angularVelocity;
                if (!rotation)
                    return;
                var rotationSeparate = rotation.separateAxes;
                var rotationType = rotation.type;
                if (value.enable) {
                    if (rotationSeparate) {
                        shaDat.addDefine(ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_ROTATIONOVERLIFETIMESEPERATE);
                    }
                    else {
                        shaDat.addDefine(ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_ROTATIONOVERLIFETIME);
                    }
                    switch (rotationType) {
                        case 0:
                            if (this._mulDefMode) {
                                shaDat.addDefine(ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_ROTATIONOVERLIFETIMECONSTANT);
                                if (rotationSeparate) {
                                    shaDat.setVector3(ShuriKenParticle3DShaderDeclaration.ROLANGULARVELOCITYCONSTSEPRARATE, rotation.constantSeparate);
                                }
                                else {
                                    shaDat.setNumber(ShuriKenParticle3DShaderDeclaration.ROLANGULARVELOCITYCONST, rotation.constant);
                                }
                            }
                            else {
                                if (rotationSeparate) {
                                    rotation._constantXGradientDdata._formatData();
                                    rotation._constantYGradientDdata._formatData();
                                    rotation._constantZGradientDdata._formatData();
                                    shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.ROLANGULARVELOCITYGRADIENTX, rotation._constantXGradientDdata._elements);
                                    shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.ROLANGULARVELOCITYGRADIENTXMAX, rotation._constantXGradientDdata._elements);
                                    shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.ROLANGULARVELOCITYGRADIENTY, rotation._constantYGradientDdata._elements);
                                    shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.ROLANGULARVELOCITYGRADIENTYMAX, rotation._constantYGradientDdata._elements);
                                    shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.ROLANGULARVELOCITYGRADIENTZ, rotation._constantZGradientDdata._elements);
                                    shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.ROLANGULARVELOCITYGRADIENTZMAX, rotation._constantZGradientDdata._elements);
                                }
                                else {
                                    rotation._constantGradientDdata._formatData();
                                    shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.ROLANGULARVELOCITYGRADIENT, rotation._constantGradientDdata._elements);
                                    shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.ROLANGULARVELOCITYGRADIENTMAX, rotation._constantGradientDdata._elements);
                                }
                            }
                            break;
                        case 1:
                            if (this._mulDefMode)
                                shaDat.addDefine(ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_ROTATIONOVERLIFETIMECURVE);
                            if (rotationSeparate) {
                                rotation.gradientX._formatData();
                                rotation.gradientY._formatData();
                                rotation.gradientZ._formatData();
                                shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.ROLANGULARVELOCITYGRADIENTX, rotation.gradientX._elements);
                                shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.ROLANGULARVELOCITYGRADIENTY, rotation.gradientY._elements);
                                shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.ROLANGULARVELOCITYGRADIENTZ, rotation.gradientZ._elements);
                                if (!this._mulDefMode) {
                                    shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.ROLANGULARVELOCITYGRADIENTXMAX, rotation.gradientX._elements);
                                    shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.ROLANGULARVELOCITYGRADIENTYMAX, rotation.gradientY._elements);
                                    shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.ROLANGULARVELOCITYGRADIENTZMAX, rotation.gradientZ._elements);
                                }
                            }
                            else {
                                rotation.gradient._formatData();
                                shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.ROLANGULARVELOCITYGRADIENT, rotation.gradient._elements);
                                if (!this._mulDefMode)
                                    shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.ROLANGULARVELOCITYGRADIENTMAX, rotation.gradient._elements);
                            }
                            break;
                        case 2:
                            if (this._mulDefMode) {
                                shaDat.addDefine(ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_ROTATIONOVERLIFETIMERANDOMCONSTANTS);
                                if (rotationSeparate) {
                                    shaDat.setVector3(ShuriKenParticle3DShaderDeclaration.ROLANGULARVELOCITYCONSTSEPRARATE, rotation.constantMinSeparate);
                                    shaDat.setVector3(ShuriKenParticle3DShaderDeclaration.ROLANGULARVELOCITYCONSTMAXSEPRARATE, rotation.constantMaxSeparate);
                                }
                                else {
                                    shaDat.setNumber(ShuriKenParticle3DShaderDeclaration.ROLANGULARVELOCITYCONST, rotation.constantMin);
                                    shaDat.setNumber(ShuriKenParticle3DShaderDeclaration.ROLANGULARVELOCITYCONSTMAX, rotation.constantMax);
                                }
                            }
                            else {
                                if (rotationSeparate) {
                                    rotation._constantXMinGradientDdata._formatData();
                                    rotation._constantXMaxGradientDdata._formatData();
                                    rotation._constantYMinGradientDdata._formatData();
                                    rotation._constantYMaxGradientDdata._formatData();
                                    rotation._constantZMinGradientDdata._formatData();
                                    rotation._constantZMaxGradientDdata._formatData();
                                    shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.ROLANGULARVELOCITYGRADIENTX, rotation._constantXMinGradientDdata._elements);
                                    shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.ROLANGULARVELOCITYGRADIENTXMAX, rotation._constantXMaxGradientDdata._elements);
                                    shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.ROLANGULARVELOCITYGRADIENTY, rotation._constantYMinGradientDdata._elements);
                                    shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.ROLANGULARVELOCITYGRADIENTYMAX, rotation._constantYMaxGradientDdata._elements);
                                    shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.ROLANGULARVELOCITYGRADIENTZ, rotation._constantZMinGradientDdata._elements);
                                    shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.ROLANGULARVELOCITYGRADIENTZMAX, rotation._constantZMaxGradientDdata._elements);
                                }
                                else {
                                    rotation._constantMinGradientDdata._formatData();
                                    rotation._constantMaxGradientDdata._formatData();
                                    shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.ROLANGULARVELOCITYGRADIENT, rotation._constantMinGradientDdata._elements);
                                    shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.ROLANGULARVELOCITYGRADIENTMAX, rotation._constantMaxGradientDdata._elements);
                                }
                            }
                            break;
                        case 3:
                            if (this._mulDefMode)
                                shaDat.addDefine(ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_ROTATIONOVERLIFETIMERANDOMCURVES);
                            if (rotationSeparate) {
                                rotation.gradientXMin._formatData();
                                rotation.gradientXMax._formatData();
                                rotation.gradientYMin._formatData();
                                rotation.gradientYMax._formatData();
                                rotation.gradientZMin._formatData();
                                rotation.gradientZMax._formatData();
                                shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.ROLANGULARVELOCITYGRADIENTX, rotation.gradientXMin._elements);
                                shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.ROLANGULARVELOCITYGRADIENTXMAX, rotation.gradientXMax._elements);
                                shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.ROLANGULARVELOCITYGRADIENTY, rotation.gradientYMin._elements);
                                shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.ROLANGULARVELOCITYGRADIENTYMAX, rotation.gradientYMax._elements);
                                shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.ROLANGULARVELOCITYGRADIENTZ, rotation.gradientZMin._elements);
                                shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.ROLANGULARVELOCITYGRADIENTZMAX, rotation.gradientZMax._elements);
                            }
                            else {
                                rotation.gradientMin._formatData();
                                rotation.gradientMax._formatData();
                                shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.ROLANGULARVELOCITYGRADIENT, rotation.gradientMin._elements);
                                shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.ROLANGULARVELOCITYGRADIENTMAX, rotation.gradientMax._elements);
                            }
                            break;
                    }
                }
            }
        }
        get textureSheetAnimation() {
            return this._textureSheetAnimation;
        }
        set textureSheetAnimation(value) {
            var shaDat = this._ownerRender._baseRenderNode.shaderData;
            this._textureSheetAnimation = value;
            if (this._mulDefMode) {
                shaDat.removeDefine(ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_TEXTURESHEETANIMATIONCURVE);
                shaDat.removeDefine(ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_TEXTURESHEETANIMATIONRANDOMCURVE);
            }
            if (value && value.enable) {
                var frameOverTime = value.frame;
                var textureAniType = frameOverTime.type;
                shaDat.setNumber(ShuriKenParticle3DShaderDeclaration.TEXTURESHEETANIMATIONCYCLES, value.cycles);
                var title = value.tiles;
                var _uvLengthE = this._uvLength;
                _uvLengthE.x = 1.0 / title.x;
                _uvLengthE.y = 1.0 / title.y;
                shaDat.setVector2(ShuriKenParticle3DShaderDeclaration.TEXTURESHEETANIMATIONSUBUVLENGTH, this._uvLength);
                if (value.enable) {
                    switch (textureAniType) {
                        case 1:
                            frameOverTime.frameOverTimeData._formatData();
                            shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.TEXTURESHEETANIMATIONGRADIENTUVS, frameOverTime.frameOverTimeData._elements);
                            if (this._mulDefMode) {
                                shaDat.addDefine(ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_TEXTURESHEETANIMATIONCURVE);
                            }
                            else {
                                shaDat.addDefine(ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_TEXTURESHEETANIMATIONRANDOMCURVE);
                                shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.TEXTURESHEETANIMATIONGRADIENTMAXUVS, frameOverTime.frameOverTimeData._elements);
                            }
                            break;
                        case 3:
                            frameOverTime.frameOverTimeDataMin._formatData();
                            frameOverTime.frameOverTimeDataMax._formatData();
                            if (!this._mulDefMode)
                                shaDat.addDefine(ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_TEXTURESHEETANIMATIONRANDOMCURVE);
                            shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.TEXTURESHEETANIMATIONGRADIENTUVS, frameOverTime.frameOverTimeDataMin._elements);
                            shaDat.setBuffer(ShuriKenParticle3DShaderDeclaration.TEXTURESHEETANIMATIONGRADIENTMAXUVS, frameOverTime.frameOverTimeDataMax._elements);
                            break;
                        default:
                            shaDat.removeDefine(ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_TEXTURESHEETANIMATIONRANDOMCURVE);
                            break;
                    }
                }
            }
            else {
                shaDat.removeDefine(ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_TEXTURESHEETANIMATIONRANDOMCURVE);
            }
        }
        constructor(render, meshTopology = Laya.MeshTopology.Triangles, drawType = Laya.DrawType.DrawElement) {
            super(meshTopology, drawType);
            this._bounds = null;
            this._gravityOffset = new Laya.Vector2();
            this._customBounds = null;
            this._useCustomBounds = false;
            this._owner = null;
            this._ownerRender = null;
            this._vertices = null;
            this._floatCountPerVertex = 0;
            this._startLifeTimeIndex = 0;
            this._timeIndex = 0;
            this._simulationUV_Index = 0;
            this._simulateUpdate = false;
            this._firstActiveElement = 0;
            this._firstNewElement = 0;
            this._firstFreeElement = 0;
            this._firstRetiredElement = 0;
            this._drawCounter = 0;
            this._bufferMaxParticles = 0;
            this._emission = null;
            this._shape = null;
            this._isEmitting = false;
            this._isPlaying = false;
            this._isPaused = false;
            this._playStartDelay = 0;
            this._frameRateTime = 0;
            this._emissionTime = 0;
            this._totalDelayTime = 0;
            this._emissionDistance = 0;
            this._emissionLastPosition = new Laya.Vector3();
            this._burstsIndex = 0;
            this._velocityOverLifetime = null;
            this._colorOverLifetime = null;
            this._sizeOverLifetime = null;
            this._rotationOverLifetime = null;
            this._textureSheetAnimation = null;
            this._startLifetimeType = 0;
            this._startLifetimeConstant = 0;
            this._startLifeTimeGradient = null;
            this._startLifetimeConstantMin = 0;
            this._startLifetimeConstantMax = 0;
            this._startLifeTimeGradientMin = null;
            this._startLifeTimeGradientMax = null;
            this._maxStartLifetime = 0;
            this._uvLength = new Laya.Vector2();
            this._vertexStride = 0;
            this._indexStride = 0;
            this._vertexBuffer = null;
            this._indexBuffer = null;
            this._bufferState = new Laya.BufferState();
            this._updateMask = 0;
            this._currentTime = 0;
            this._startUpdateLoopCount = 0;
            this._rand = null;
            this._randomSeeds = null;
            this.duration = 0;
            this.looping = false;
            this.prewarm = false;
            this.startDelayType = 0;
            this.startDelay = 0;
            this.startDelayMin = 0;
            this.startDelayMax = 0;
            this.startSpeedType = 0;
            this.startSpeedConstant = 0;
            this.startSpeedConstantMin = 0;
            this.startSpeedConstantMax = 0;
            this.dragType = 0;
            this.dragConstant = 0;
            this.dragSpeedConstantMin = 0;
            this.dragSpeedConstantMax = 0;
            this.threeDStartSize = false;
            this.startSizeType = 0;
            this.startSizeConstant = 0;
            this.startSizeConstantSeparate = null;
            this.startSizeConstantMin = 0;
            this.startSizeConstantMax = 0;
            this.startSizeConstantMinSeparate = null;
            this.startSizeConstantMaxSeparate = null;
            this.threeDStartRotation = false;
            this.startRotationType = 0;
            this.startRotationConstant = 0;
            this.startRotationConstantSeparate = null;
            this.startRotationConstantMin = 0;
            this.startRotationConstantMax = 0;
            this.startRotationConstantMinSeparate = null;
            this.startRotationConstantMaxSeparate = null;
            this.randomizeRotationDirection = 0;
            this.startColorType = 0;
            this.startColorConstant = new Laya.Vector4(1, 1, 1, 1);
            this.startColorConstantMin = new Laya.Vector4(0, 0, 0, 0);
            this.startColorConstantMax = new Laya.Vector4(1, 1, 1, 1);
            this.startColorGradient = new Laya.Gradient();
            this.startColorGradientMin = new Laya.Gradient();
            this.startColorGradientMax = new Laya.Gradient();
            this.gravityModifier = 0;
            this.simulationSpace = 0;
            this.simulationSpeed = 1.0;
            this.scaleMode = 1;
            this.playOnAwake = false;
            this.randomSeed = null;
            this.autoRandomSeed = false;
            this.isPerformanceMode = false;
            this._gradientKeyCount8 = false;
            this._mulDefMode = ShuriKenParticle3DShaderDeclaration.mulShaderDefineMode;
            this.indexFormat = Laya.IndexFormat.UInt16;
            this._firstActiveElement = 0;
            this._firstNewElement = 0;
            this._firstFreeElement = 0;
            this._firstRetiredElement = 0;
            this._owner = render.owner;
            this._ownerRender = render;
            this._useCustomBounds = false;
            this._currentTime = 0;
            this._bounds = new Laya.Bounds(new Laya.Vector3(-Number.MAX_VALUE, -Number.MAX_VALUE, -Number.MAX_VALUE), new Laya.Vector3(Number.MAX_VALUE, Number.MAX_VALUE, Number.MAX_VALUE));
            this.bufferState = this._bufferState = new Laya.BufferState();
            this._isEmitting = false;
            this._isPlaying = false;
            this._isPaused = false;
            this._burstsIndex = 0;
            this._frameRateTime = 0;
            this._emissionTime = 0;
            this._totalDelayTime = 0;
            this._simulateUpdate = false;
            this._bufferMaxParticles = 1;
            this.duration = 5.0;
            this.looping = true;
            this.prewarm = false;
            this.startDelayType = 0;
            this.startDelay = 0.0;
            this.startDelayMin = 0.0;
            this.startDelayMax = 0.0;
            this._startLifetimeType = 0;
            this._startLifetimeConstant = 5.0;
            this._startLifeTimeGradient = new Laya.GradientDataNumber();
            this._startLifetimeConstantMin = 0.0;
            this._startLifetimeConstantMax = 5.0;
            this._startLifeTimeGradientMin = new Laya.GradientDataNumber();
            this._startLifeTimeGradientMax = new Laya.GradientDataNumber();
            this._maxStartLifetime = 5.0;
            this.startSpeedType = 0;
            this.startSpeedConstant = 5.0;
            this.startSpeedConstantMin = 0.0;
            this.startSpeedConstantMax = 5.0;
            this.dragType = 0;
            this.dragConstant = 0;
            this.dragSpeedConstantMin = 0;
            this.dragSpeedConstantMax = 0;
            this.threeDStartSize = false;
            this.startSizeType = 0;
            this.startSizeConstant = 1;
            this.startSizeConstantSeparate = new Laya.Vector3(1, 1, 1);
            this.startSizeConstantMin = 0;
            this.startSizeConstantMax = 1;
            this.startSizeConstantMinSeparate = new Laya.Vector3(0, 0, 0);
            this.startSizeConstantMaxSeparate = new Laya.Vector3(1, 1, 1);
            this.threeDStartRotation = false;
            this.startRotationType = 0;
            this.startRotationConstant = 0;
            this.startRotationConstantSeparate = new Laya.Vector3(0, 0, 0);
            this.startRotationConstantMin = 0.0;
            this.startRotationConstantMax = 0.0;
            this.startRotationConstantMinSeparate = new Laya.Vector3(0, 0, 0);
            this.startRotationConstantMaxSeparate = new Laya.Vector3(0, 0, 0);
            this.gravityModifier = 0.0;
            this.simulationSpace = 1;
            this.scaleMode = 1;
            this.playOnAwake = true;
            this._rand = new Laya.Rand(0);
            this.autoRandomSeed = true;
            this.randomSeed = new Uint32Array(1);
            this._randomSeeds = new Uint32Array(ShurikenParticleSystem._RANDOMOFFSET.length);
            this.isPerformanceMode = true;
            this._emission = new Emission();
            this._emission.enable = true;
        }
        _getVertexBuffer(index = 0) {
            if (index === 0)
                return this._vertexBuffer;
            else
                return null;
        }
        _getIndexBuffer() {
            return this._indexBuffer;
        }
        _generateBounds() {
            var particleRender = this._ownerRender;
            var boundsMin = this._bounds.getMin();
            var boundsMax = this._bounds.getMax();
            var time = 0;
            switch (this._startLifetimeType) {
                case 0:
                    time = this._startLifetimeConstant;
                    break;
                case 2:
                    time = this._startLifetimeConstantMax;
                    break;
            }
            var speedOrigan = 0;
            switch (this.startSpeedType) {
                case 0:
                    speedOrigan = this.startSpeedConstant;
                    break;
                case 2:
                    speedOrigan = this.startSpeedConstantMax;
                    break;
            }
            var maxSizeScale = 0;
            if (this.threeDStartSize) {
                switch (this.startSizeType) {
                    case 0:
                        maxSizeScale = Math.max(this.startSizeConstantSeparate.x, this.startSizeConstantSeparate.y, this.startSizeConstantSeparate.z);
                        break;
                    case 2:
                        maxSizeScale = Math.max(this.startSizeConstantMaxSeparate.x, this.startSizeConstantMaxSeparate.y, this.startSizeConstantMaxSeparate.z);
                        break;
                }
            }
            else {
                switch (this.startSizeType) {
                    case 0:
                        maxSizeScale = this.startSizeConstant;
                        break;
                    case 2:
                        maxSizeScale = this.startSizeConstantMax;
                        break;
                }
            }
            var zDirectionSpeed = _tempVector30;
            var fDirectionSpeed = _tempVector31;
            var zEmisionOffsetXYZ = _tempVector32;
            var fEmisionOffsetXYZ = _tempVector33;
            zDirectionSpeed.setValue(0, 0, 1);
            fDirectionSpeed.setValue(0, 0, 0);
            zEmisionOffsetXYZ.setValue(0, 0, 0);
            fEmisionOffsetXYZ.setValue(0, 0, 0);
            if (this._shape && this._shape.enable) {
                switch (this._shape.shapeType) {
                    case exports.ParticleSystemShapeType.Sphere:
                        var sphere = this._shape;
                        zDirectionSpeed.setValue(1, 1, 1);
                        fDirectionSpeed.setValue(1, 1, 1);
                        zEmisionOffsetXYZ.setValue(sphere.radius, sphere.radius, sphere.radius);
                        fEmisionOffsetXYZ.setValue(sphere.radius, sphere.radius, sphere.radius);
                        break;
                    case exports.ParticleSystemShapeType.Hemisphere:
                        var hemiShpere = this._shape;
                        zDirectionSpeed.setValue(1, 1, 1);
                        fDirectionSpeed.setValue(1, 1, 1);
                        zEmisionOffsetXYZ.setValue(hemiShpere.radius, hemiShpere.radius, hemiShpere.radius);
                        fEmisionOffsetXYZ.setValue(hemiShpere.radius, hemiShpere.radius, 0.0);
                        break;
                    case exports.ParticleSystemShapeType.Cone:
                        var cone = this._shape;
                        if (cone.emitType == 0 || cone.emitType == 1) {
                            var angle = cone.angle;
                            var sinAngle = Math.sin(angle);
                            zDirectionSpeed.setValue(sinAngle, sinAngle, 1.0);
                            fDirectionSpeed.setValue(sinAngle, sinAngle, 0.0);
                            zEmisionOffsetXYZ.setValue(cone.radius, cone.radius, 0.0);
                            fEmisionOffsetXYZ.setValue(cone.radius, cone.radius, 0.0);
                            break;
                        }
                        else if (cone.emitType == 2 || cone.emitType == 3) {
                            var angle = cone.angle;
                            var sinAngle = Math.sin(angle);
                            var coneLength = cone.length;
                            zDirectionSpeed.setValue(sinAngle, sinAngle, 1.0);
                            fDirectionSpeed.setValue(sinAngle, sinAngle, 0.0);
                            var tanAngle = Math.tan(angle);
                            var rPLCT = cone.radius + coneLength * tanAngle;
                            zEmisionOffsetXYZ.setValue(rPLCT, rPLCT, coneLength);
                            fEmisionOffsetXYZ.setValue(rPLCT, rPLCT, 0.0);
                        }
                        break;
                    case exports.ParticleSystemShapeType.Box:
                        var box = this._shape;
                        if (this._shape.randomDirection != 0) {
                            zDirectionSpeed.setValue(1, 1, 1);
                            fDirectionSpeed.setValue(1, 1, 1);
                        }
                        zEmisionOffsetXYZ.setValue(box.x / 2, box.y / 2, box.z / 2);
                        fEmisionOffsetXYZ.setValue(box.x / 2, box.y / 2, box.z / 2);
                        break;
                    case exports.ParticleSystemShapeType.Circle:
                        var circle = this._shape;
                        zDirectionSpeed.setValue(1, 1, 1);
                        fDirectionSpeed.setValue(1, 1, 1);
                        zEmisionOffsetXYZ.setValue(circle.radius, circle.radius, 0);
                        fEmisionOffsetXYZ.setValue(circle.radius, circle.radius, 0);
                        break;
                }
            }
            var meshSize = 0;
            var meshMode = particleRender.renderMode == 4;
            switch (particleRender.renderMode) {
                case 0:
                case 1:
                case 2:
                case 3:
                    meshSize = ShurikenParticleSystem.halfKSqrtOf2;
                    break;
                case 4:
                    if (particleRender.mesh) {
                        var meshBounds = particleRender.mesh.bounds;
                        meshSize = Math.sqrt(Math.pow(meshBounds.getExtent().x, 2.0) + Math.pow(meshBounds.getExtent().y, 2.0) + Math.pow(meshBounds.getExtent().z, 2.0));
                    }
                    else {
                        meshSize = ShurikenParticleSystem.halfKSqrtOf2;
                    }
                    break;
            }
            var endSizeOffset = _tempVector36;
            endSizeOffset.setValue(1, 1, 1);
            if (this._sizeOverLifetime && this._sizeOverLifetime.enable) {
                var gradientSize = this._sizeOverLifetime.size;
                var maxSize = gradientSize.getMaxSizeInGradient(meshMode);
                endSizeOffset.setValue(maxSize, maxSize, maxSize);
            }
            var offsetSize = meshSize * maxSizeScale;
            Laya.Vector3.scale(endSizeOffset, offsetSize, endSizeOffset);
            var speedZOffset = _tempVector34;
            var speedFOffset = _tempVector35;
            if (speedOrigan > 0) {
                Laya.Vector3.scale(zDirectionSpeed, speedOrigan, speedZOffset);
                Laya.Vector3.scale(fDirectionSpeed, speedOrigan, speedFOffset);
            }
            else {
                Laya.Vector3.scale(zDirectionSpeed, -speedOrigan, speedFOffset);
                Laya.Vector3.scale(fDirectionSpeed, -speedOrigan, speedZOffset);
            }
            if (this._velocityOverLifetime && this._velocityOverLifetime.enable) {
                var gradientVelocity = this._velocityOverLifetime.velocity;
                var velocitySpeedOffset = _tempVector37;
                velocitySpeedOffset.setValue(0, 0, 0);
                switch (gradientVelocity.type) {
                    case 0:
                        gradientVelocity.constant.cloneTo(velocitySpeedOffset);
                        break;
                    case 2:
                        gradientVelocity.constantMax.cloneTo(velocitySpeedOffset);
                        break;
                    case 1:
                        var curveX = gradientVelocity.gradientX.getAverageValue();
                        var curveY = gradientVelocity.gradientY.getAverageValue();
                        var curveZ = gradientVelocity.gradientZ.getAverageValue();
                        velocitySpeedOffset.setValue(curveX, curveY, curveZ);
                        break;
                    case 3:
                        var xMax = gradientVelocity.gradientXMax.getAverageValue();
                        var yMax = gradientVelocity.gradientYMax.getAverageValue();
                        var zMax = gradientVelocity.gradientZMax.getAverageValue();
                        velocitySpeedOffset.setValue(xMax, yMax, zMax);
                        break;
                }
                if (this._velocityOverLifetime.space == 1) {
                    Laya.Vector3.transformV3ToV3(velocitySpeedOffset, this._owner.transform.worldMatrix, velocitySpeedOffset);
                }
                Laya.Vector3.add(speedZOffset, velocitySpeedOffset, speedZOffset);
                Laya.Vector3.subtract(speedFOffset, velocitySpeedOffset, speedFOffset);
                Laya.Vector3.max(speedZOffset, Laya.Vector3.ZERO, speedZOffset);
                Laya.Vector3.max(speedFOffset, Laya.Vector3.ZERO, speedFOffset);
            }
            Laya.Vector3.scale(speedZOffset, time, speedZOffset);
            Laya.Vector3.scale(speedFOffset, time, speedFOffset);
            var gravity = this.gravityModifier;
            if (gravity != 0) {
                var gravityOffset = 0.5 * ShurikenParticleSystem.g * gravity * time * time;
                var speedZOffsetY = speedZOffset.y - gravityOffset;
                var speedFOffsetY = speedFOffset.y + gravityOffset;
                speedZOffsetY = speedZOffsetY > 0 ? speedZOffsetY : 0;
                speedFOffsetY = speedFOffsetY > 0 ? speedFOffsetY : 0;
                this._gravityOffset.setValue(speedZOffset.y - speedZOffsetY, speedFOffsetY - speedFOffset.y);
            }
            Laya.Vector3.add(speedZOffset, endSizeOffset, boundsMax);
            Laya.Vector3.add(boundsMax, zEmisionOffsetXYZ, boundsMax);
            Laya.Vector3.add(speedFOffset, endSizeOffset, boundsMin);
            Laya.Vector3.add(boundsMin, fEmisionOffsetXYZ, boundsMin);
            Laya.Vector3.scale(boundsMin, -1, boundsMin);
            this._bounds.setMin(boundsMin);
            this._bounds.setMax(boundsMax);
        }
        get customBounds() {
            return this._customBounds;
        }
        set customBounds(value) {
            if (value) {
                this._useCustomBounds = true;
                if (!this._customBounds) {
                    this._customBounds = new Laya.Bounds(new Laya.Vector3(), new Laya.Vector3());
                    this._ownerRender.geometryBounds = this._customBounds;
                }
                this._customBounds = value;
            }
            else {
                this._useCustomBounds = false;
                this._customBounds = null;
                this._ownerRender.geometryBounds = null;
            }
        }
        _simulationSupported() {
            if (this.simulationSpace == 0 && this._emission.emissionRateOverDistance > 0) {
                return false;
            }
            return true;
        }
        _updateEmission() {
            if (!this.isAlive)
                return;
            if (this._simulateUpdate) {
                this._simulateUpdate = false;
            }
            else {
                let elapsedTime = ((this._startUpdateLoopCount !== Laya.Stat.loopCount && !this._isPaused) && this._owner._scene) ? this._owner._scene.timer.delta / 1000.0 : 0;
                elapsedTime = Math.min(ShurikenParticleSystem._maxElapsedTime, elapsedTime * this.simulationSpeed);
                this._updateParticles(elapsedTime);
            }
        }
        _updateParticles(elapsedTime) {
            if (this._ownerRender.renderMode === 4 && !this._ownerRender.mesh)
                return;
            this._currentTime += elapsedTime;
            this._retireActiveParticles();
            this._freeRetiredParticles();
            this._totalDelayTime += elapsedTime;
            if (this._totalDelayTime < this._playStartDelay) {
                return;
            }
            if (this._emission.enable && this._isEmitting && !this._isPaused) {
                this._advanceTime(elapsedTime, this._currentTime);
                if (this._emission.emissionRateOverDistance > 0) {
                    this._advanceDistance(this._currentTime, elapsedTime);
                }
                let position = this._owner.transform.position;
                position.cloneTo(this._emissionLastPosition);
            }
        }
        _updateParticlesSimulationRestart(time) {
            this._firstActiveElement = 0;
            this._firstNewElement = 0;
            this._firstFreeElement = 0;
            this._firstRetiredElement = 0;
            this._burstsIndex = 0;
            this._frameRateTime = time;
            this._emissionTime = 0;
            this._emissionDistance = 0;
            this._totalDelayTime = 0;
            this._currentTime = time;
            var delayTime = time;
            if (delayTime < this._playStartDelay) {
                this._totalDelayTime = delayTime;
                return;
            }
            if (this._emission.enable) {
                this._advanceTime(time, time);
                if (this._emission.emissionRateOverDistance > 0) {
                    this._advanceDistance(this._currentTime, time);
                }
                let position = this._owner.transform.position;
                position.cloneTo(this._emissionLastPosition);
            }
        }
        _retireActiveParticles() {
            const epsilon = 0.0001;
            while (this._firstActiveElement != this._firstNewElement) {
                var index = this._firstActiveElement * this._floatCountPerVertex * this._vertexStride;
                var timeIndex = index + this._timeIndex;
                var particleAge = this._currentTime - this._vertices[timeIndex];
                if (particleAge + epsilon < this._vertices[index + this._startLifeTimeIndex])
                    break;
                this._vertices[timeIndex] = this._drawCounter;
                this._firstActiveElement++;
                if (this._firstActiveElement >= this._bufferMaxParticles)
                    this._firstActiveElement = 0;
            }
        }
        _freeRetiredParticles() {
            while (this._firstRetiredElement != this._firstActiveElement) {
                this._drawCounter - this._vertices[this._firstRetiredElement * this._floatCountPerVertex * this._vertexStride + this._timeIndex];
                this._firstRetiredElement++;
                if (this._firstRetiredElement >= this._bufferMaxParticles)
                    this._firstRetiredElement = 0;
            }
        }
        _burst(fromTime, toTime) {
            var totalEmitCount = 0;
            var bursts = this._emission._bursts;
            for (var n = bursts.length; this._burstsIndex < n; this._burstsIndex++) {
                var burst = bursts[this._burstsIndex];
                var burstTime = burst.time;
                if (fromTime <= burstTime && burstTime < toTime) {
                    var emitCount;
                    if (this.autoRandomSeed) {
                        emitCount = Laya.MathUtil.lerp(burst.minCount, burst.maxCount, Math.random());
                    }
                    else {
                        this._rand.seed = this._randomSeeds[0];
                        emitCount = Laya.MathUtil.lerp(burst.minCount, burst.maxCount, this._rand.getFloat());
                        this._randomSeeds[0] = this._rand.seed;
                    }
                    totalEmitCount += emitCount;
                }
                else {
                    break;
                }
            }
            return totalEmitCount;
        }
        _advanceTime(elapsedTime, emitTime) {
            var i;
            var lastEmissionTime = this._emissionTime;
            this._emissionTime += elapsedTime;
            var totalEmitCount = 0;
            if (this._emissionTime > this.duration) {
                if (this.looping) {
                    totalEmitCount += this._burst(lastEmissionTime, this._emissionTime);
                    this._emissionTime -= this.duration;
                    this._burstsIndex = 0;
                    totalEmitCount += this._burst(0, this._emissionTime);
                }
                else {
                    totalEmitCount = Math.min(this.maxParticles - this.aliveParticleCount, totalEmitCount);
                    for (i = 0; i < totalEmitCount; i++)
                        this.emit(emitTime, elapsedTime);
                    this._isPlaying = false;
                    this.stop();
                    return;
                }
            }
            else {
                totalEmitCount += this._burst(lastEmissionTime, this._emissionTime);
            }
            totalEmitCount = Math.min(this.maxParticles - this.aliveParticleCount, totalEmitCount);
            for (i = 0; i < totalEmitCount; i++)
                this.emit(emitTime, elapsedTime);
            var emissionRate = this._emission.emissionRate;
            if (emissionRate > 0) {
                var minEmissionTime = 1 / emissionRate;
                this._frameRateTime += minEmissionTime;
                this._frameRateTime = this._currentTime - (this._currentTime - this._frameRateTime) % this._maxStartLifetime;
                while (this._frameRateTime <= emitTime) {
                    if (this.emit(this._frameRateTime, elapsedTime)) {
                        this._frameRateTime += minEmissionTime;
                    }
                    else
                        break;
                }
                this._frameRateTime = Math.floor(emitTime / minEmissionTime) * minEmissionTime;
            }
        }
        _advanceDistance(emitTime, elapsedTime) {
            if (this._ownerRender.renderMode === 4 && !this._ownerRender.mesh)
                return;
            let position = this._owner.transform.position;
            let offsetDistance = Laya.Vector3.distance(position, this._emissionLastPosition);
            let rateOverDistance = this._emission.emissionRateOverDistance;
            let distance = this._emissionDistance + offsetDistance;
            let ed = 1.0 / rateOverDistance;
            if (distance > ed) {
                let emitCount = distance * rateOverDistance;
                emitCount = Math.floor(emitCount);
                emitCount = Math.min(this.maxParticles - this.aliveParticleCount, emitCount);
                for (let index = 0; index < emitCount; index++) {
                    this.emit(emitTime, elapsedTime);
                }
                this._emissionDistance = 0;
            }
            else {
                this._emissionDistance = distance;
            }
        }
        _initBufferDatas() {
            if (this._vertexBuffer && this._vertexBuffer._buffer) {
                var memorySize = this._vertexBuffer._byteLength + this._indexBuffer.indexCount * 2;
                this._vertexBuffer.destroy();
                this._indexBuffer.destroy();
                Laya.Resource._addMemory(-memorySize, -memorySize);
            }
            var render = this._ownerRender;
            var renderMode = render.renderMode;
            if (renderMode !== -1 && this.maxParticles > 0) {
                var indices, i, j, m, indexOffset, perPartOffset, vertexDeclaration;
                var vbMemorySize = 0, memorySize = 0;
                var mesh = render.mesh;
                if (renderMode === 4) {
                    if (mesh) {
                        vertexDeclaration = VertexShurikenParticleMesh.vertexDeclaration;
                        this._floatCountPerVertex = vertexDeclaration.vertexStride / 4;
                        this._simulationUV_Index = vertexDeclaration.getVertexElementByUsage(VertexShuriKenParticle.PARTICLE_SIMULATIONUV).offset / 4;
                        this._startLifeTimeIndex = 12;
                        this._timeIndex = 16;
                        this._vertexStride = mesh._vertexCount;
                        var totalVertexCount = this._bufferMaxParticles * this._vertexStride;
                        var vbCount = Math.floor(totalVertexCount / 65535) + 1;
                        var lastVBVertexCount = totalVertexCount % 65535;
                        if (vbCount > 1) {
                            throw new Error("the maxParticleCount multiply mesh vertexCount is large than 65535.");
                        }
                        vbMemorySize = vertexDeclaration.vertexStride * lastVBVertexCount;
                        this._vertexBuffer = Laya.Laya3DRender.renderOBJCreate.createVertexBuffer3D(vbMemorySize, Laya.BufferUsage.Dynamic, false);
                        this._vertexBuffer.vertexDeclaration = vertexDeclaration;
                        this._vertices = new Float32Array(this._floatCountPerVertex * lastVBVertexCount);
                        this._indexStride = mesh._indexBuffer.indexCount;
                        var indexDatas = mesh._indexBuffer.getData();
                        var indexCount = this._bufferMaxParticles * this._indexStride;
                        this._indexBuffer = Laya.Laya3DRender.renderOBJCreate.createIndexBuffer3D(Laya.IndexFormat.UInt16, indexCount, Laya.BufferUsage.Static, false);
                        indices = new Uint16Array(indexCount);
                        memorySize = vbMemorySize + indexCount * 2;
                        indexOffset = 0;
                        for (i = 0; i < this._bufferMaxParticles; i++) {
                            var indexValueOffset = i * this._vertexStride;
                            for (j = 0, m = indexDatas.length; j < m; j++)
                                indices[indexOffset++] = indexValueOffset + indexDatas[j];
                        }
                        this._indexBuffer.setData(indices);
                        this._bufferState.applyState([this._vertexBuffer], this._indexBuffer);
                        this.bufferState = this._bufferState;
                    }
                }
                else {
                    vertexDeclaration = VertexShurikenParticleBillboard.vertexDeclaration;
                    this._floatCountPerVertex = vertexDeclaration.vertexStride / 4;
                    this._startLifeTimeIndex = 7;
                    this._simulationUV_Index = vertexDeclaration.getVertexElementByUsage(VertexShuriKenParticle.PARTICLE_SIMULATIONUV).offset / 4;
                    this._timeIndex = 11;
                    this._vertexStride = 4;
                    vbMemorySize = vertexDeclaration.vertexStride * this._bufferMaxParticles * this._vertexStride;
                    this._vertexBuffer = Laya.Laya3DRender.renderOBJCreate.createVertexBuffer3D(vbMemorySize, Laya.BufferUsage.Dynamic, false);
                    this._vertexBuffer.vertexDeclaration = vertexDeclaration;
                    this._vertices = new Float32Array(this._floatCountPerVertex * this._bufferMaxParticles * this._vertexStride);
                    for (i = 0; i < this._bufferMaxParticles; i++) {
                        perPartOffset = i * this._floatCountPerVertex * this._vertexStride;
                        this._vertices[perPartOffset] = -0.5;
                        this._vertices[perPartOffset + 1] = -0.5;
                        this._vertices[perPartOffset + 2] = 0;
                        this._vertices[perPartOffset + 3] = 1;
                        perPartOffset += this._floatCountPerVertex;
                        this._vertices[perPartOffset] = 0.5;
                        this._vertices[perPartOffset + 1] = -0.5;
                        this._vertices[perPartOffset + 2] = 1;
                        this._vertices[perPartOffset + 3] = 1;
                        perPartOffset += this._floatCountPerVertex;
                        this._vertices[perPartOffset] = 0.5;
                        this._vertices[perPartOffset + 1] = 0.5;
                        this._vertices[perPartOffset + 2] = 1;
                        this._vertices[perPartOffset + 3] = 0;
                        perPartOffset += this._floatCountPerVertex;
                        this._vertices[perPartOffset] = -0.5;
                        this._vertices[perPartOffset + 1] = 0.5;
                        this._vertices[perPartOffset + 2] = 0;
                        this._vertices[perPartOffset + 3] = 0;
                    }
                    this._indexStride = 6;
                    this._indexBuffer = Laya.Laya3DRender.renderOBJCreate.createIndexBuffer3D(Laya.IndexFormat.UInt16, this._bufferMaxParticles * 6, Laya.BufferUsage.Static, false);
                    indices = new Uint16Array(this._bufferMaxParticles * 6);
                    for (i = 0; i < this._bufferMaxParticles; i++) {
                        indexOffset = i * 6;
                        var firstVertex = i * this._vertexStride, secondVertex = firstVertex + 2;
                        indices[indexOffset++] = firstVertex;
                        indices[indexOffset++] = secondVertex;
                        indices[indexOffset++] = firstVertex + 1;
                        indices[indexOffset++] = firstVertex;
                        indices[indexOffset++] = firstVertex + 3;
                        indices[indexOffset++] = secondVertex;
                    }
                    this._indexBuffer.setData(indices);
                    memorySize = vbMemorySize + this._bufferMaxParticles * 6 * 2;
                    this._bufferState.applyState([this._vertexBuffer], this._indexBuffer);
                    this.bufferState = this._bufferState;
                }
                Laya.Resource._addMemory(memorySize, memorySize);
            }
        }
        destroy() {
            super.destroy();
            if (this._vertexBuffer) {
                var memorySize = this._vertexBuffer._byteLength;
                Laya.Resource._addMemory(-memorySize, -memorySize);
                this._vertexBuffer.destroy();
                this._vertexBuffer = null;
            }
            if (this._indexBuffer) {
                var memorySize = this._indexBuffer._byteLength;
                Laya.Resource._addMemory(-memorySize, -memorySize);
                this._indexBuffer.destroy();
                this._indexBuffer = null;
            }
            this._emission.destroy();
            this._bounds = null;
            this._customBounds = null;
            this._bufferState = null;
            this._owner = null;
            this._vertices = null;
            this._indexBuffer = null;
            this._emission = null;
            this._shape = null;
            this._startLifeTimeGradient = null;
            this._startLifeTimeGradientMin = null;
            this._startLifeTimeGradientMax = null;
            this.startSizeConstantSeparate = null;
            this.startSizeConstantMinSeparate = null;
            this.startSizeConstantMaxSeparate = null;
            this.startRotationConstantSeparate = null;
            this.startRotationConstantMinSeparate = null;
            this.startRotationConstantMaxSeparate = null;
            this.startColorConstant = null;
            this.startColorConstantMin = null;
            this.startColorConstantMax = null;
            this.startColorGradient = null;
            this.startColorGradientMin = null;
            this.startColorGradientMax = null;
            this._velocityOverLifetime = null;
            this._colorOverLifetime = null;
            this._sizeOverLifetime = null;
            this._rotationOverLifetime = null;
            this._textureSheetAnimation = null;
        }
        emit(time, elapsedTime) {
            var position = _tempPosition;
            var direction = _tempDirection;
            if (this._shape && this._shape.enable) {
                if (this.autoRandomSeed)
                    this._shape.generatePositionAndDirection(position, direction);
                else
                    this._shape.generatePositionAndDirection(position, direction, this._rand, this._randomSeeds);
            }
            else {
                position.x = position.y = position.z = 0;
                direction.x = direction.y = 0;
                direction.z = 1;
            }
            return this.addParticle(position, direction, time, elapsedTime);
        }
        addParticle(position, direction, time, elapsedTime) {
            Laya.Vector3.normalize(direction, direction);
            var nextFreeParticle = this._firstFreeElement + 1;
            if (nextFreeParticle >= this._bufferMaxParticles)
                nextFreeParticle = 0;
            if (nextFreeParticle === this._firstRetiredElement)
                return false;
            var transform = this._owner.transform;
            ShurikenParticleData.create(this, this._ownerRender);
            var particleAge = this._currentTime - time;
            if (particleAge >= ShurikenParticleData.startLifeTime)
                return true;
            let pos, rot;
            if (this.simulationSpace == 0) {
                rot = transform.rotation;
                pos = tempV3$1;
                let timeT = (this._currentTime - time) / elapsedTime;
                timeT = Laya.MathUtil.clamp01(timeT);
                Laya.Vector3.lerp(transform.position, this._emissionLastPosition, timeT, pos);
            }
            var startSpeed;
            switch (this.startSpeedType) {
                case 0:
                    startSpeed = this.startSpeedConstant;
                    break;
                case 2:
                    if (this.autoRandomSeed) {
                        startSpeed = Laya.MathUtil.lerp(this.startSpeedConstantMin, this.startSpeedConstantMax, Math.random());
                    }
                    else {
                        this._rand.seed = this._randomSeeds[8];
                        startSpeed = Laya.MathUtil.lerp(this.startSpeedConstantMin, this.startSpeedConstantMax, this._rand.getFloat());
                        this._randomSeeds[8] = this._rand.seed;
                    }
                    break;
            }
            var randomVelocityX, randomVelocityY, randomVelocityZ, randomColor, randomSize, randomRotation, randomTextureAnimation;
            var needRandomVelocity = this._velocityOverLifetime && this._velocityOverLifetime.enable;
            if (needRandomVelocity) {
                var velocityType = this._velocityOverLifetime.velocity.type;
                if (velocityType === 2 || velocityType === 3) {
                    if (this.autoRandomSeed) {
                        randomVelocityX = Math.random();
                        randomVelocityY = Math.random();
                        randomVelocityZ = Math.random();
                    }
                    else {
                        this._rand.seed = this._randomSeeds[9];
                        randomVelocityX = this._rand.getFloat();
                        randomVelocityY = this._rand.getFloat();
                        randomVelocityZ = this._rand.getFloat();
                        this._randomSeeds[9] = this._rand.seed;
                    }
                }
                else {
                    needRandomVelocity = false;
                }
            }
            else {
                needRandomVelocity = false;
            }
            var needRandomColor = this._colorOverLifetime && this._colorOverLifetime.enable;
            if (needRandomColor) {
                var colorType = this._colorOverLifetime.color.type;
                if (colorType === 3) {
                    if (this.autoRandomSeed) {
                        randomColor = Math.random();
                    }
                    else {
                        this._rand.seed = this._randomSeeds[10];
                        randomColor = this._rand.getFloat();
                        this._randomSeeds[10] = this._rand.seed;
                    }
                }
                else {
                    needRandomColor = false;
                }
            }
            else {
                needRandomColor = false;
            }
            var needRandomSize = this._sizeOverLifetime && this._sizeOverLifetime.enable;
            if (needRandomSize) {
                var sizeType = this._sizeOverLifetime.size.type;
                if (sizeType === 3) {
                    if (this.autoRandomSeed) {
                        randomSize = Math.random();
                    }
                    else {
                        this._rand.seed = this._randomSeeds[11];
                        randomSize = this._rand.getFloat();
                        this._randomSeeds[11] = this._rand.seed;
                    }
                }
                else {
                    needRandomSize = false;
                }
            }
            else {
                needRandomSize = false;
            }
            var needRandomRotation = this._rotationOverLifetime && this._rotationOverLifetime.enable;
            if (needRandomRotation) {
                var rotationType = this._rotationOverLifetime.angularVelocity.type;
                if (rotationType === 2 || rotationType === 3) {
                    if (this.autoRandomSeed) {
                        randomRotation = Math.random();
                    }
                    else {
                        this._rand.seed = this._randomSeeds[12];
                        randomRotation = this._rand.getFloat();
                        this._randomSeeds[12] = this._rand.seed;
                    }
                }
                else {
                    needRandomRotation = false;
                }
            }
            else {
                needRandomRotation = false;
            }
            var needRandomTextureAnimation = this._textureSheetAnimation && this._textureSheetAnimation.enable;
            if (needRandomTextureAnimation) {
                var textureAnimationType = this._textureSheetAnimation.frame.type;
                if (textureAnimationType === 3) {
                    if (this.autoRandomSeed) {
                        randomTextureAnimation = Math.random();
                    }
                    else {
                        this._rand.seed = this._randomSeeds[15];
                        randomTextureAnimation = this._rand.getFloat();
                        this._randomSeeds[15] = this._rand.seed;
                    }
                }
                else {
                    needRandomTextureAnimation = false;
                }
            }
            else {
                needRandomTextureAnimation = false;
            }
            var startIndex = this._firstFreeElement * this._floatCountPerVertex * this._vertexStride;
            var subU = ShurikenParticleData.startUVInfo[0];
            var subV = ShurikenParticleData.startUVInfo[1];
            var startU = ShurikenParticleData.startUVInfo[2];
            var startV = ShurikenParticleData.startUVInfo[3];
            var meshVertices, meshVertexStride, meshPosOffset, meshCorOffset, meshUVOffset, meshVertexIndex;
            var render = this._ownerRender;
            if (render.renderMode === 4) {
                var meshVB = render.mesh._vertexBuffer;
                meshVertices = meshVB.getFloat32Data();
                var meshVertexDeclaration = meshVB.vertexDeclaration;
                meshPosOffset = meshVertexDeclaration.getVertexElementByUsage(Laya.VertexMesh.MESH_POSITION0)._offset / 4;
                var colorElement = meshVertexDeclaration.getVertexElementByUsage(Laya.VertexMesh.MESH_COLOR0);
                meshCorOffset = colorElement ? colorElement._offset / 4 : -1;
                var uvElement = meshVertexDeclaration.getVertexElementByUsage(Laya.VertexMesh.MESH_TEXTURECOORDINATE0);
                meshUVOffset = uvElement ? uvElement._offset / 4 : -1;
                meshVertexStride = meshVertexDeclaration.vertexStride / 4;
                meshVertexIndex = 0;
            }
            for (var i = startIndex, n = startIndex + this._floatCountPerVertex * this._vertexStride; i < n; i += this._floatCountPerVertex) {
                var offset;
                if (render.renderMode === 4) {
                    offset = i;
                    var vertexOffset = meshVertexStride * (meshVertexIndex++);
                    var meshOffset = vertexOffset + meshPosOffset;
                    this._vertices[offset++] = meshVertices[meshOffset++];
                    this._vertices[offset++] = meshVertices[meshOffset++];
                    this._vertices[offset++] = meshVertices[meshOffset];
                    if (meshCorOffset === -1) {
                        this._vertices[offset++] = 1.0;
                        this._vertices[offset++] = 1.0;
                        this._vertices[offset++] = 1.0;
                        this._vertices[offset++] = 1.0;
                    }
                    else {
                        meshOffset = vertexOffset + meshCorOffset;
                        this._vertices[offset++] = meshVertices[meshOffset++];
                        this._vertices[offset++] = meshVertices[meshOffset++];
                        this._vertices[offset++] = meshVertices[meshOffset++];
                        this._vertices[offset++] = meshVertices[meshOffset];
                    }
                    if (meshUVOffset === -1) {
                        this._vertices[offset++] = 0.0;
                        this._vertices[offset++] = 0.0;
                    }
                    else {
                        meshOffset = vertexOffset + meshUVOffset;
                        this._vertices[offset++] = meshVertices[meshOffset++];
                        this._vertices[offset++] = meshVertices[meshOffset];
                    }
                }
                else {
                    offset = i + 4;
                }
                this._vertices[offset++] = position.x;
                this._vertices[offset++] = position.y;
                this._vertices[offset++] = position.z;
                this._vertices[offset++] = ShurikenParticleData.startLifeTime;
                this._vertices[offset++] = direction.x;
                this._vertices[offset++] = direction.y;
                this._vertices[offset++] = direction.z;
                this._vertices[offset++] = time;
                this._vertices[offset++] = ShurikenParticleData.startColor.x;
                this._vertices[offset++] = ShurikenParticleData.startColor.y;
                this._vertices[offset++] = ShurikenParticleData.startColor.z;
                this._vertices[offset++] = ShurikenParticleData.startColor.w;
                this._vertices[offset++] = ShurikenParticleData.startSize[0];
                this._vertices[offset++] = ShurikenParticleData.startSize[1];
                this._vertices[offset++] = ShurikenParticleData.startSize[2];
                this._vertices[offset++] = ShurikenParticleData.startRotation[0];
                this._vertices[offset++] = ShurikenParticleData.startRotation[1];
                this._vertices[offset++] = ShurikenParticleData.startRotation[2];
                this._vertices[offset++] = startSpeed;
                needRandomColor && (this._vertices[offset + 1] = randomColor);
                needRandomSize && (this._vertices[offset + 2] = randomSize);
                needRandomRotation && (this._vertices[offset + 3] = randomRotation);
                needRandomTextureAnimation && (this._vertices[offset + 4] = randomTextureAnimation);
                if (needRandomVelocity) {
                    this._vertices[offset + 5] = randomVelocityX;
                    this._vertices[offset + 6] = randomVelocityY;
                    this._vertices[offset + 7] = randomVelocityZ;
                }
                switch (this.simulationSpace) {
                    case 0:
                        offset += 8;
                        this._vertices[offset++] = pos.x;
                        this._vertices[offset++] = pos.y;
                        this._vertices[offset++] = pos.z;
                        this._vertices[offset++] = rot.x;
                        this._vertices[offset++] = rot.y;
                        this._vertices[offset++] = rot.z;
                        this._vertices[offset++] = rot.w;
                        break;
                    case 1:
                        break;
                    default:
                        throw new Error("unknown simulationSpace: " + this.simulationSpace);
                }
                offset = i + this._simulationUV_Index;
                this._vertices[offset++] = startU;
                this._vertices[offset++] = startV;
                this._vertices[offset++] = subU;
                this._vertices[offset] = subV;
            }
            this._firstFreeElement = nextFreeParticle;
            return true;
        }
        addNewParticlesToVertexBuffer() {
            var start;
            var byteStride = this._vertexStride * this._floatCountPerVertex * 4;
            if (this._firstNewElement < this._firstFreeElement) {
                start = this._firstNewElement * byteStride;
                this._vertexBuffer.setData(this._vertices.buffer, start, start, (this._firstFreeElement - this._firstNewElement) * byteStride);
            }
            else {
                start = this._firstNewElement * byteStride;
                this._vertexBuffer.setData(this._vertices.buffer, start, start, (this._bufferMaxParticles - this._firstNewElement) * byteStride);
                if (this._firstFreeElement > 0) {
                    this._vertexBuffer.setData(this._vertices.buffer, 0, 0, this._firstFreeElement * byteStride);
                }
            }
            this._firstNewElement = this._firstFreeElement;
        }
        _getType() {
            return ShurikenParticleSystem._type;
        }
        _prepareRender(state) {
            let t = performance.now();
            if (this._updateMask != Laya.Stat.loopCount) {
                this._updateMask = Laya.Stat.loopCount;
                this._updateEmission();
                if (this._firstNewElement != this._firstFreeElement)
                    this.addNewParticlesToVertexBuffer();
                this._drawCounter++;
            }
            Laya.LayaGL.statAgent.recordTimeData(Laya.StatElement.T_ShurikenUpdate, performance.now() - t);
            if (this._firstActiveElement != this._firstFreeElement)
                return true;
            else
                return false;
        }
        _updateRenderParams(state) {
            var indexCount;
            this.clearRenderParams();
            if (this._firstActiveElement < this._firstFreeElement) {
                indexCount = (this._firstFreeElement - this._firstActiveElement) * this._indexStride;
                this.setDrawElemenParams(indexCount, 2 * this._firstActiveElement * this._indexStride);
            }
            else {
                indexCount = (this._bufferMaxParticles - this._firstActiveElement) * this._indexStride;
                this.setDrawElemenParams(indexCount, 2 * this._firstActiveElement * this._indexStride);
                if (this._firstFreeElement > 0) {
                    indexCount = this._firstFreeElement * this._indexStride;
                    this.setDrawElemenParams(indexCount, 0);
                }
            }
        }
        play() {
            this._burstsIndex = 0;
            this._isEmitting = true;
            this._isPlaying = true;
            this._isPaused = false;
            this._emissionTime = 0;
            this._emissionDistance = 0;
            this._owner.transform.position.cloneTo(this._emissionLastPosition);
            this._totalDelayTime = 0;
            if (!this.autoRandomSeed) {
                for (var i = 0, n = this._randomSeeds.length; i < n; i++)
                    this._randomSeeds[i] = this.randomSeed[0] + ShurikenParticleSystem._RANDOMOFFSET[i];
            }
            switch (this.startDelayType) {
                case 0:
                    this._playStartDelay = this.startDelay;
                    break;
                case 1:
                    if (this.autoRandomSeed) {
                        this._playStartDelay = Laya.MathUtil.lerp(this.startDelayMin, this.startDelayMax, Math.random());
                    }
                    else {
                        this._rand.seed = this._randomSeeds[2];
                        this._playStartDelay = Laya.MathUtil.lerp(this.startDelayMin, this.startDelayMax, this._rand.getFloat());
                        this._randomSeeds[2] = this._rand.seed;
                    }
                    break;
                default:
                    throw new Error("unknown startDelayType: " + this.startDelayType);
            }
            this._frameRateTime = this._currentTime + this._playStartDelay;
            this._startUpdateLoopCount = Laya.Stat.loopCount;
        }
        pause() {
            this._isPaused = true;
        }
        simulate(time, restart = true) {
            this._simulateUpdate = true;
            if (restart) {
                this._updateParticlesSimulationRestart(time);
            }
            else {
                this._isPaused = false;
                this._updateParticles(time);
            }
            this.pause();
        }
        stop() {
            this._burstsIndex = 0;
            this._isEmitting = false;
            this._emissionTime = 0;
        }
        cloneTo(destObject) {
            destObject._useCustomBounds = this._useCustomBounds;
            (this._customBounds) && (this._customBounds.cloneTo(destObject._customBounds));
            destObject.duration = this.duration;
            destObject.looping = this.looping;
            destObject.prewarm = this.prewarm;
            destObject.startDelayType = this.startDelayType;
            destObject.startDelay = this.startDelay;
            destObject.startDelayMin = this.startDelayMin;
            destObject.startDelayMax = this.startDelayMax;
            destObject._maxStartLifetime = this._maxStartLifetime;
            destObject.startLifetimeType = this._startLifetimeType;
            destObject.startLifetimeConstant = this._startLifetimeConstant;
            this._startLifeTimeGradient.cloneTo(destObject.startLifeTimeGradient);
            destObject.startLifetimeConstantMin = this._startLifetimeConstantMin;
            destObject.startLifetimeConstantMax = this._startLifetimeConstantMax;
            this._startLifeTimeGradientMin.cloneTo(destObject.startLifeTimeGradientMin);
            this._startLifeTimeGradientMax.cloneTo(destObject.startLifeTimeGradientMax);
            destObject.startSpeedType = this.startSpeedType;
            destObject.startSpeedConstant = this.startSpeedConstant;
            destObject.startSpeedConstantMin = this.startSpeedConstantMin;
            destObject.startSpeedConstantMax = this.startSpeedConstantMax;
            destObject.dragType = this.dragType;
            destObject.dragConstant = this.dragConstant;
            destObject.dragSpeedConstantMax = this.dragSpeedConstantMax;
            destObject.dragSpeedConstantMin = this.dragSpeedConstantMin;
            destObject.threeDStartSize = this.threeDStartSize;
            destObject.startSizeType = this.startSizeType;
            destObject.startSizeConstant = this.startSizeConstant;
            this.startSizeConstantSeparate.cloneTo(destObject.startSizeConstantSeparate);
            destObject.startSizeConstantMin = this.startSizeConstantMin;
            destObject.startSizeConstantMax = this.startSizeConstantMax;
            this.startSizeConstantMinSeparate.cloneTo(destObject.startSizeConstantMinSeparate);
            this.startSizeConstantMaxSeparate.cloneTo(destObject.startSizeConstantMaxSeparate);
            destObject.threeDStartRotation = this.threeDStartRotation;
            destObject.startRotationType = this.startRotationType;
            destObject.startRotationConstant = this.startRotationConstant;
            this.startRotationConstantSeparate.cloneTo(destObject.startRotationConstantSeparate);
            destObject.startRotationConstantMin = this.startRotationConstantMin;
            destObject.startRotationConstantMax = this.startRotationConstantMax;
            this.startRotationConstantMinSeparate.cloneTo(destObject.startRotationConstantMinSeparate);
            this.startRotationConstantMaxSeparate.cloneTo(destObject.startRotationConstantMaxSeparate);
            destObject.randomizeRotationDirection = this.randomizeRotationDirection;
            destObject.startColorType = this.startColorType;
            this.startColorConstant.cloneTo(destObject.startColorConstant);
            this.startColorConstantMin.cloneTo(destObject.startColorConstantMin);
            this.startColorConstantMax.cloneTo(destObject.startColorConstantMax);
            this.startColorGradient.cloneTo(destObject.startColorGradient);
            this.startColorGradientMin.cloneTo(destObject.startColorGradientMin);
            this.startColorGradientMax.cloneTo(destObject.startColorGradientMax);
            destObject.gravityModifier = this.gravityModifier;
            destObject.simulationSpace = this.simulationSpace;
            destObject.simulationSpeed = this.simulationSpeed;
            destObject.scaleMode = this.scaleMode;
            destObject.playOnAwake = this.playOnAwake;
            destObject.autoRandomSeed = this.autoRandomSeed;
            destObject.randomSeed[0] = this.randomSeed[0];
            destObject.maxParticles = this.maxParticles;
            (this._emission) && (destObject._emission = this._emission.clone());
            (this._shape) && (destObject.shape = this._shape.clone());
            (this._velocityOverLifetime) && (destObject.velocityOverLifetime = this._velocityOverLifetime.clone());
            (this._colorOverLifetime) && (destObject.colorOverLifetime = this._colorOverLifetime.clone());
            (this._sizeOverLifetime) && (destObject.sizeOverLifetime = this._sizeOverLifetime.clone());
            (this._rotationOverLifetime) && (destObject.rotationOverLifetime = this._rotationOverLifetime.clone());
            (this._textureSheetAnimation) && (destObject.textureSheetAnimation = this._textureSheetAnimation.clone());
            destObject.isPerformanceMode = this.isPerformanceMode;
            destObject.gradientKeyCount8 = this._gradientKeyCount8;
            destObject._isEmitting = this._isEmitting;
            destObject._isPlaying = this._isPlaying;
            destObject._isPaused = this._isPaused;
            destObject._playStartDelay = this._playStartDelay;
            destObject._frameRateTime = this._frameRateTime;
            destObject._emissionTime = this._emissionTime;
            destObject._totalDelayTime = this._totalDelayTime;
            destObject._burstsIndex = this._burstsIndex;
        }
        clone() {
            var dest = new ShurikenParticleSystem(null);
            this.cloneTo(dest);
            return dest;
        }
    }
    ShurikenParticleSystem._RANDOMOFFSET = new Uint32Array([0x23571a3e, 0xc34f56fe, 0x13371337, 0x12460f3b, 0x6aed452e, 0xdec4aea1, 0x96aa4de3, 0x8d2c8431, 0xf3857f6f, 0xe0fbd834, 0x13740583, 0x591bc05c, 0x40eb95e4, 0xbc524e5f, 0xaf502044, 0xa614b381, 0x1034e524, 0xfc524e5f]);
    ShurikenParticleSystem.halfKSqrtOf2 = 1.42 * 0.5;
    ShurikenParticleSystem.g = 9.8;
    ShurikenParticleSystem._maxElapsedTime = 1.0 / 3.0;
    ShurikenParticleSystem._type = Laya.GeometryElement._typeCounter++;
    const _tempVector30 = new Laya.Vector3();
    const _tempVector31 = new Laya.Vector3();
    const _tempVector32 = new Laya.Vector3();
    const _tempVector33 = new Laya.Vector3();
    const _tempVector34 = new Laya.Vector3();
    const _tempVector35 = new Laya.Vector3();
    const _tempVector36 = new Laya.Vector3();
    const _tempVector37 = new Laya.Vector3();
    const _tempPosition = new Laya.Vector3();
    const _tempDirection = new Laya.Vector3();

    const tempV3 = new Laya.Vector3(0, 0, 0);
    class ShurikenParticleInstanceSystem extends ShurikenParticleSystem {
        constructor(render) {
            super(render, Laya.MeshTopology.Triangles, Laya.DrawType.DrawElementInstance);
            this._instanceParticleVertexBuffer = null;
            this._instanceVertex = null;
        }
        _initMeshVertex(vertex, mesh) {
            let meshVertexBuffer = mesh._vertexBuffer;
            let meshVertices = meshVertexBuffer.getFloat32Data();
            let meshVertexDeclaration = meshVertexBuffer.vertexDeclaration;
            let meshPosOffset = meshVertexDeclaration.getVertexElementByUsage(Laya.VertexMesh.MESH_POSITION0)._offset / 4;
            let colorElement = meshVertexDeclaration.getVertexElementByUsage(Laya.VertexMesh.MESH_COLOR0);
            let meshColorOffset = colorElement ? colorElement._offset / 4 : -1;
            let uvElement = meshVertexDeclaration.getVertexElementByUsage(Laya.VertexMesh.MESH_TEXTURECOORDINATE0);
            let meshUVOffset = uvElement ? uvElement._offset / 4 : -1;
            let meshVertexStride = meshVertexDeclaration.vertexStride / 4;
            let meshVertexIndex = 0;
            let vertexCount = mesh.vertexCount;
            let perParticleDataCount = this._vertexBuffer.vertexDeclaration.vertexStride / 4;
            for (let index = 0; index < vertexCount; index++) {
                let startIndex = index * perParticleDataCount;
                let indexOffset = startIndex;
                let vertexOffset = meshVertexStride * meshVertexIndex++;
                let positionOffset = vertexOffset + meshPosOffset;
                vertex[indexOffset++] = meshVertices[positionOffset++];
                vertex[indexOffset++] = meshVertices[positionOffset++];
                vertex[indexOffset++] = meshVertices[positionOffset++];
                if (meshColorOffset == -1) {
                    vertex[indexOffset++] = 1;
                    vertex[indexOffset++] = 1;
                    vertex[indexOffset++] = 1;
                    vertex[indexOffset++] = 1;
                }
                else {
                    let colorOffset = vertexOffset + meshColorOffset;
                    vertex[indexOffset++] = meshVertices[colorOffset++];
                    vertex[indexOffset++] = meshVertices[colorOffset++];
                    vertex[indexOffset++] = meshVertices[colorOffset++];
                    vertex[indexOffset++] = meshVertices[colorOffset++];
                }
                if (meshUVOffset == -1) {
                    vertex[indexOffset++] = 0;
                    vertex[indexOffset++] = 0;
                }
                else {
                    let uvOffset = vertexOffset + meshUVOffset;
                    vertex[indexOffset++] = meshVertices[uvOffset++];
                    vertex[indexOffset++] = meshVertices[uvOffset++];
                }
            }
        }
        _initBufferDatas() {
            if (this._vertexBuffer) {
                this._vertexBuffer.destroy();
                this._instanceParticleVertexBuffer.destroy();
                this._indexBuffer.destroy();
                this._vertexBuffer = null;
                this._instanceParticleVertexBuffer = null;
                this._indexBuffer = null;
            }
            let render = this._ownerRender;
            let renderMode = render.renderMode;
            if (renderMode == -1 || this.maxParticles <= 0) {
                return;
            }
            if (renderMode == 4) {
                let mesh = render.mesh;
                if (mesh) {
                    let meshDeclaration = VertexShurikenParticleMesh.vertexInstanceMeshDeclaration;
                    let particleDeclaration = VertexShurikenParticleMesh.vertexInstanceParticleDeclaration;
                    this._meshIndexCount = mesh.indexCount;
                    this._simulationUV_Index = particleDeclaration.getVertexElementByUsage(VertexShuriKenParticle.PARTICLE_SIMULATIONUV).offset / 4;
                    this._floatCountPerParticleData = particleDeclaration.vertexStride / 4;
                    this._startLifeTimeIndex = particleDeclaration.getVertexElementByUsage(VertexShuriKenParticle.PARTICLE_SHAPEPOSITIONSTARTLIFETIME)._offset / 4 + 3;
                    this._timeIndex = particleDeclaration.getVertexElementByUsage(VertexShuriKenParticle.PARTICLE_DIRECTIONTIME)._offset / 4 + 3;
                    let indexCount = mesh.indexCount;
                    this._indexBuffer = Laya.Laya3DRender.renderOBJCreate.createIndexBuffer3D(mesh.indexFormat, indexCount, Laya.BufferUsage.Static, false);
                    this._indexBuffer.setData(mesh._indexBuffer.getData());
                    let meshVertexCount = mesh.vertexCount;
                    let vbSize = meshDeclaration.vertexStride * meshVertexCount;
                    this._vertexBuffer = Laya.Laya3DRender.renderOBJCreate.createVertexBuffer3D(vbSize, Laya.BufferUsage.Static, false);
                    this._vertexBuffer.vertexDeclaration = meshDeclaration;
                    let meshVertex = new Float32Array(vbSize / 4);
                    this._initMeshVertex(meshVertex, mesh);
                    this._vertexBuffer.setData(meshVertex.buffer);
                    let particleCount = this._bufferMaxParticles;
                    let particleVbSize = particleCount * particleDeclaration.vertexStride;
                    this._instanceVertex = new Float32Array(particleVbSize / 4);
                    this._instanceParticleVertexBuffer = Laya.Laya3DRender.renderOBJCreate.createVertexBuffer3D(particleVbSize, Laya.BufferUsage.Dynamic, false);
                    this._instanceParticleVertexBuffer.vertexDeclaration = particleDeclaration;
                    this._instanceParticleVertexBuffer.setData(this._instanceVertex.buffer);
                    this._instanceParticleVertexBuffer.instanceBuffer = true;
                    this._bufferState.applyState([this._vertexBuffer, this._instanceParticleVertexBuffer], this._indexBuffer);
                }
            }
            else {
                let billboardDeclaration = VertexShurikenParticleBillboard.vertexInstanceMeshDeclaration;
                let particleDeclaration = VertexShurikenParticleBillboard.vertexInstanceParticleDeclaration;
                this._meshIndexCount = 6;
                this._simulationUV_Index = particleDeclaration.getVertexElementByUsage(VertexShuriKenParticle.PARTICLE_SIMULATIONUV).offset / 4;
                this._floatCountPerParticleData = particleDeclaration.vertexStride / 4;
                this._startLifeTimeIndex = particleDeclaration.getVertexElementByUsage(VertexShuriKenParticle.PARTICLE_SHAPEPOSITIONSTARTLIFETIME)._offset / 4 + 3;
                this._timeIndex = particleDeclaration.getVertexElementByUsage(VertexShuriKenParticle.PARTICLE_DIRECTIONTIME)._offset / 4 + 3;
                let indexArray = VertexShurikenParticleBillboard.billboardIndexArray;
                let indexCount = indexArray.length;
                this._indexBuffer = Laya.Laya3DRender.renderOBJCreate.createIndexBuffer3D(Laya.IndexFormat.UInt16, indexCount, Laya.BufferUsage.Static, false);
                this._indexBuffer.setData(indexArray);
                let meshVBSize = this._meshIndexCount * billboardDeclaration.vertexStride;
                this._vertexBuffer = Laya.Laya3DRender.renderOBJCreate.createVertexBuffer3D(meshVBSize, Laya.BufferUsage.Static, false);
                this._vertexBuffer.vertexDeclaration = billboardDeclaration;
                this._vertexBuffer.setData(VertexShurikenParticleBillboard.billboardVertexArray.buffer);
                let particleCount = this._bufferMaxParticles;
                let particleVbSize = particleCount * particleDeclaration.vertexStride;
                this._instanceVertex = new Float32Array(particleVbSize / 4);
                this._instanceParticleVertexBuffer = Laya.Laya3DRender.renderOBJCreate.createVertexBuffer3D(particleVbSize, Laya.BufferUsage.Dynamic, false);
                this._instanceParticleVertexBuffer.vertexDeclaration = particleDeclaration;
                this._instanceParticleVertexBuffer.setData(this._instanceVertex.buffer);
                this._instanceParticleVertexBuffer.instanceBuffer = true;
                this._bufferState.applyState([this._vertexBuffer, this._instanceParticleVertexBuffer], this._indexBuffer);
            }
        }
        _retireActiveParticles() {
            if (this._instanceParticleVertexBuffer == null)
                return;
            const epsilon = 0.0001;
            let firstActive = this._firstActiveElement;
            while (this._firstActiveElement != this._firstNewElement) {
                let index = this._firstActiveElement * this._floatCountPerParticleData;
                let timeIndex = index + this._timeIndex;
                let particleAge = this._currentTime - this._instanceVertex[timeIndex];
                if (particleAge + epsilon < this._instanceVertex[index + this._startLifeTimeIndex]) {
                    break;
                }
                this._instanceVertex[timeIndex] = this._drawCounter;
                this._firstActiveElement++;
                if (this._firstActiveElement >= this._bufferMaxParticles) {
                    this._firstActiveElement = 0;
                }
            }
            if (this._firstActiveElement != firstActive) {
                let byteStride = this._floatCountPerParticleData * 4;
                if (this._firstActiveElement < this._firstFreeElement) {
                    let activeStart = this._firstActiveElement * byteStride;
                    this._instanceParticleVertexBuffer.setData(this._instanceVertex.buffer, 0, activeStart, (this._firstFreeElement - this._firstActiveElement) * byteStride);
                }
                else {
                    let start = this._firstActiveElement * byteStride;
                    let a = this._bufferMaxParticles - this._firstActiveElement;
                    this._instanceParticleVertexBuffer.setData(this._instanceVertex.buffer, 0, start, a * byteStride);
                    if (this._firstFreeElement > 0) {
                        this._instanceParticleVertexBuffer.setData(this._instanceVertex.buffer, a * byteStride, 0, this._firstFreeElement * byteStride);
                    }
                }
            }
        }
        _freeRetiredParticles() {
            while (this._firstRetiredElement != this._firstActiveElement) {
                this._drawCounter - this._instanceVertex[this._firstRetiredElement * this._floatCountPerParticleData + this._timeIndex];
                this._firstRetiredElement++;
                if (this._firstRetiredElement >= this._bufferMaxParticles)
                    this._firstRetiredElement = 0;
            }
        }
        addParticle(position, direction, time, elapsedTime) {
            Laya.Vector3.normalize(direction, direction);
            let nextFreeParticle = this._firstFreeElement + 1;
            if (nextFreeParticle >= this._bufferMaxParticles) {
                nextFreeParticle = 0;
            }
            if (nextFreeParticle == this._firstRetiredElement) {
                return false;
            }
            let transform = this._owner.transform;
            ShurikenParticleData.create(this, this._ownerRender);
            let particleAge = this._currentTime - time;
            if (particleAge >= ShurikenParticleData.startLifeTime) {
                return true;
            }
            let pos, rot;
            if (this.simulationSpace == 0) {
                rot = transform.rotation;
                pos = tempV3;
                let timeT = (this._currentTime - time) / elapsedTime;
                timeT = Laya.MathUtil.clamp01(timeT);
                Laya.Vector3.lerp(transform.position, this._emissionLastPosition, timeT, pos);
            }
            let startSpeed = 0;
            switch (this.startSpeedType) {
                case 0:
                    startSpeed = this.startSpeedConstant;
                    break;
                case 2:
                    if (this.autoRandomSeed) {
                        startSpeed = Laya.MathUtil.lerp(this.startSpeedConstantMin, this.startSpeedConstantMax, Math.random());
                    }
                    else {
                        this._rand.seed = this._randomSeeds[8];
                        startSpeed = Laya.MathUtil.lerp(this.startSpeedConstantMin, this.startSpeedConstantMax, this._rand.getFloat());
                        this._randomSeeds[8] = this._rand.seed;
                    }
                    break;
            }
            let randomVelocityX, randomVelocityY, randomVelocityZ;
            let needRandomVelocity = this._velocityOverLifetime && this._velocityOverLifetime.enable;
            if (needRandomVelocity) {
                let velocityType = this._velocityOverLifetime.velocity.type;
                if (velocityType == 2 || velocityType == 3) {
                    if (this.autoRandomSeed) {
                        randomVelocityX = Math.random();
                        randomVelocityY = Math.random();
                        randomVelocityZ = Math.random();
                    }
                    else {
                        this._rand.seed = this._randomSeeds[9];
                        randomVelocityX = this._rand.getFloat();
                        randomVelocityY = this._rand.getFloat();
                        randomVelocityZ = this._rand.getFloat();
                        this._randomSeeds[9] = this._rand.seed;
                    }
                }
                else {
                    needRandomVelocity = false;
                }
            }
            else {
                needRandomVelocity = false;
            }
            let randomColor;
            let needRandomColor = this._colorOverLifetime && this._colorOverLifetime.enable;
            if (needRandomColor) {
                let colorType = this._colorOverLifetime.color.type;
                if (colorType == 3) {
                    if (this.autoRandomSeed) {
                        randomColor = Math.random();
                    }
                    else {
                        this._rand.seed = this._randomSeeds[10];
                        randomColor = this._rand.getFloat();
                        this._randomSeeds[10] = this._rand.seed;
                    }
                }
                else {
                    needRandomColor = false;
                }
            }
            else {
                needRandomColor = false;
            }
            let randomSize;
            let needRandomSize = this._sizeOverLifetime && this._sizeOverLifetime.enable;
            if (needRandomSize) {
                let sizeType = this._sizeOverLifetime.size.type;
                if (sizeType == 3) {
                    if (this.autoRandomSeed) {
                        randomSize = Math.random();
                    }
                    else {
                        this._rand.seed = this._randomSeeds[11];
                        randomSize = this._rand.getFloat();
                        this.randomSeed[11] = this._rand.seed;
                    }
                }
                else {
                    needRandomSize = false;
                }
            }
            else {
                needRandomSize = false;
            }
            let randomRotation;
            let needRandomRotation = this._rotationOverLifetime && this._rotationOverLifetime.enable;
            if (needRandomRotation) {
                let rotationType = this._rotationOverLifetime.angularVelocity.type;
                if (rotationType == 2 || rotationType == 3) {
                    if (this.autoRandomSeed) {
                        randomRotation = Math.random();
                    }
                    else {
                        this._rand.seed = this._randomSeeds[12];
                        randomRotation = this._rand.getFloat();
                        this._randomSeeds[12] = this._rand.seed;
                    }
                }
                else {
                    needRandomRotation = false;
                }
            }
            else {
                needRandomRotation = false;
            }
            let randomTextureAnimation;
            let needRandomTextureAnimation = this._textureSheetAnimation && this._textureSheetAnimation.enable;
            if (needRandomTextureAnimation) {
                let textureAnimationType = this._textureSheetAnimation.frame.type;
                if (textureAnimationType == 3) {
                    if (this.autoRandomSeed) {
                        randomTextureAnimation = Math.random();
                    }
                    else {
                        this._rand.seed = this._randomSeeds[15];
                        randomTextureAnimation = this._rand.getFloat();
                        this._randomSeeds[15] = this._rand.seed;
                    }
                }
                else {
                    needRandomTextureAnimation = false;
                }
            }
            else {
                needRandomTextureAnimation = false;
            }
            let subU = ShurikenParticleData.startUVInfo[0];
            let subV = ShurikenParticleData.startUVInfo[1];
            let startU = ShurikenParticleData.startUVInfo[2];
            let startV = ShurikenParticleData.startUVInfo[3];
            let render = this._ownerRender;
            if (render.renderMode == 4) ;
            let startIndex = this._firstFreeElement * this._floatCountPerParticleData;
            let offset = startIndex;
            this._instanceVertex[offset++] = position.x;
            this._instanceVertex[offset++] = position.y;
            this._instanceVertex[offset++] = position.z;
            this._instanceVertex[offset++] = ShurikenParticleData.startLifeTime;
            this._instanceVertex[offset++] = direction.x;
            this._instanceVertex[offset++] = direction.y;
            this._instanceVertex[offset++] = direction.z;
            this._instanceVertex[offset++] = time;
            this._instanceVertex[offset++] = ShurikenParticleData.startColor.x;
            this._instanceVertex[offset++] = ShurikenParticleData.startColor.y;
            this._instanceVertex[offset++] = ShurikenParticleData.startColor.z;
            this._instanceVertex[offset++] = ShurikenParticleData.startColor.w;
            this._instanceVertex[offset++] = ShurikenParticleData.startSize[0];
            this._instanceVertex[offset++] = ShurikenParticleData.startSize[1];
            this._instanceVertex[offset++] = ShurikenParticleData.startSize[2];
            this._instanceVertex[offset++] = ShurikenParticleData.startRotation[0];
            this._instanceVertex[offset++] = ShurikenParticleData.startRotation[1];
            this._instanceVertex[offset++] = ShurikenParticleData.startRotation[2];
            this._instanceVertex[offset++] = startSpeed;
            needRandomColor && (this._instanceVertex[offset + 1] = randomColor);
            needRandomSize && (this._instanceVertex[offset + 2] = randomSize);
            needRandomRotation && (this._instanceVertex[offset + 3] = randomRotation);
            needRandomTextureAnimation && (this._instanceVertex[offset + 4] = randomTextureAnimation);
            if (needRandomVelocity) {
                this._instanceVertex[offset + 5] = randomVelocityX;
                this._instanceVertex[offset + 6] = randomVelocityY;
                this._instanceVertex[offset + 7] = randomVelocityZ;
            }
            switch (this.simulationSpace) {
                case 0:
                    offset += 8;
                    this._instanceVertex[offset++] = pos.x;
                    this._instanceVertex[offset++] = pos.y;
                    this._instanceVertex[offset++] = pos.z;
                    this._instanceVertex[offset++] = rot.x;
                    this._instanceVertex[offset++] = rot.y;
                    this._instanceVertex[offset++] = rot.z;
                    this._instanceVertex[offset++] = rot.w;
                    break;
                case 1:
                    break;
                default:
                    throw new Error("ShurikenParticleMaterial: SimulationSpace value is invalid.");
            }
            offset = startIndex + this._simulationUV_Index;
            this._instanceVertex[offset++] = startU;
            this._instanceVertex[offset++] = startV;
            this._instanceVertex[offset++] = subU;
            this._instanceVertex[offset++] = subV;
            this._firstFreeElement = nextFreeParticle;
            return true;
        }
        addNewParticlesToVertexBuffer() {
            let byteStride = this._floatCountPerParticleData * 4;
            if (this._firstActiveElement < this._firstFreeElement) {
                let start = this._firstActiveElement * byteStride;
                this._instanceParticleVertexBuffer.setData(this._instanceVertex.buffer, 0, start, (this._firstFreeElement - this._firstActiveElement) * byteStride);
            }
            else {
                let start = this._firstActiveElement * byteStride;
                let a = this._bufferMaxParticles - this._firstActiveElement;
                this._instanceParticleVertexBuffer.setData(this._instanceVertex.buffer, 0, start, a * byteStride);
                if (this._firstFreeElement > 0) {
                    this._instanceParticleVertexBuffer.setData(this._instanceVertex.buffer, a * byteStride, 0, this._firstFreeElement * byteStride);
                }
            }
            this._firstNewElement = this._firstFreeElement;
        }
        _updateRenderParams(stage) {
            this.clearRenderParams();
            if (this._firstActiveElement < this._firstFreeElement) {
                let indexCount = this._firstFreeElement - this._firstActiveElement;
                this.setDrawElemenParams(this._meshIndexCount, 0);
                this.instanceCount = indexCount;
            }
            else {
                let indexCount = this._bufferMaxParticles - this._firstActiveElement;
                if (this._firstFreeElement > 0) {
                    indexCount += this._firstFreeElement;
                }
                this.setDrawElemenParams(this._meshIndexCount, 0);
                this.instanceCount = indexCount;
            }
        }
        destroy() {
            super.destroy();
            if (this._indexBuffer) {
                this._indexBuffer.destroy();
            }
            if (this._vertexBuffer) {
                this._vertexBuffer.destroy();
            }
            if (this._instanceParticleVertexBuffer) {
                this._instanceParticleVertexBuffer.destroy();
            }
            this._instanceVertex = null;
            this._meshIndexCount = null;
            this._meshFloatCountPreVertex = null;
        }
    }

    class ShurikenParticleMaterial extends Laya.Material {
        static __initDefine__() {
            ShurikenParticleMaterial.SHADERDEFINE_DIFFUSEMAP = Laya.Shader3D.getDefineByName("DIFFUSEMAP");
            ShurikenParticleMaterial.SHADERDEFINE_TINTCOLOR = Laya.Shader3D.getDefineByName("TINTCOLOR");
            ShurikenParticleMaterial.SHADERDEFINE_ADDTIVEFOG = Laya.Shader3D.getDefineByName("ADDTIVEFOG");
            ShurikenParticleMaterial.DIFFUSETEXTURE = Laya.Shader3D.propertyNameToID("u_texture");
            ShurikenParticleMaterial.TINTCOLOR = Laya.Shader3D.propertyNameToID("u_Tintcolor");
            ShurikenParticleMaterial.TILINGOFFSET = Laya.Shader3D.propertyNameToID("u_TilingOffset");
        }
        get color() {
            return this._shaderValues.getColor(ShurikenParticleMaterial.TINTCOLOR);
        }
        set color(value) {
            if (value)
                this._shaderValues.addDefine(ShurikenParticleMaterial.SHADERDEFINE_TINTCOLOR);
            else
                this._shaderValues.removeDefine(ShurikenParticleMaterial.SHADERDEFINE_TINTCOLOR);
            this._shaderValues.setColor(ShurikenParticleMaterial.TINTCOLOR, value);
        }
        get tilingOffset() {
            return this._shaderValues.getVector(ShurikenParticleMaterial.TILINGOFFSET);
        }
        set tilingOffset(value) {
            if (value) {
                this._shaderValues.setVector(ShurikenParticleMaterial.TILINGOFFSET, value);
            }
            else {
                this._shaderValues.getVector(ShurikenParticleMaterial.TILINGOFFSET).setValue(1.0, 1.0, 0.0, 0.0);
            }
        }
        get texture() {
            return this._shaderValues.getTexture(ShurikenParticleMaterial.DIFFUSETEXTURE);
        }
        set texture(value) {
            if (value)
                this._shaderValues.addDefine(ShurikenParticleMaterial.SHADERDEFINE_DIFFUSEMAP);
            else
                this._shaderValues.removeDefine(ShurikenParticleMaterial.SHADERDEFINE_DIFFUSEMAP);
            this._shaderValues.setTexture(ShurikenParticleMaterial.DIFFUSETEXTURE, value);
        }
        constructor() {
            super();
            this.setShaderName("PARTICLESHURIKEN");
            this.renderMode = ShurikenParticleMaterial.RENDERMODE_ALPHABLENDED;
        }
        clone() {
            var dest = new ShurikenParticleMaterial();
            this.cloneTo(dest);
            return dest;
        }
        set renderMode(value) {
            switch (value) {
                case ShurikenParticleMaterial.RENDERMODE_ADDTIVE:
                    this.renderQueue = Laya.Material.RENDERQUEUE_TRANSPARENT;
                    this.depthWrite = false;
                    this.cull = Laya.RenderState.CULL_NONE;
                    this.blend = Laya.RenderState.BLEND_ENABLE_ALL;
                    this.blendSrc = Laya.RenderState.BLENDPARAM_SRC_ALPHA;
                    this.blendDst = Laya.RenderState.BLENDPARAM_ONE;
                    this.alphaTest = false;
                    this._shaderValues.addDefine(ShurikenParticleMaterial.SHADERDEFINE_ADDTIVEFOG);
                    break;
                case ShurikenParticleMaterial.RENDERMODE_ALPHABLENDED:
                    this.renderQueue = Laya.Material.RENDERQUEUE_TRANSPARENT;
                    this.depthWrite = false;
                    this.cull = Laya.RenderState.CULL_NONE;
                    this.blend = Laya.RenderState.BLEND_ENABLE_ALL;
                    this.blendSrc = Laya.RenderState.BLENDPARAM_SRC_ALPHA;
                    this.blendDst = Laya.RenderState.BLENDPARAM_ONE_MINUS_SRC_ALPHA;
                    this.alphaTest = false;
                    this._shaderValues.removeDefine(ShurikenParticleMaterial.SHADERDEFINE_ADDTIVEFOG);
                    break;
                default:
                    throw new Error("ShurikenParticleMaterial : renderMode value error.");
            }
        }
        get tilingOffsetX() {
            return this._MainTex_STX;
        }
        set tilingOffsetX(x) {
            this._MainTex_STX = x;
        }
        get tilingOffsetY() {
            return this._MainTex_STY;
        }
        set tilingOffsetY(y) {
            this._MainTex_STY = y;
        }
        get tilingOffsetZ() {
            return this._MainTex_STZ;
        }
        set tilingOffsetZ(z) {
            this._MainTex_STZ = z;
        }
        get tilingOffsetW() {
            return this._MainTex_STW;
        }
        set tilingOffsetW(w) {
            this._MainTex_STW = w;
        }
        get _TintColor() {
            return this.color;
        }
        set _TintColor(value) {
            this.color = value;
        }
        get _TintColorR() {
            return this.color.r;
        }
        set _TintColorR(value) {
            this.color.r = value;
        }
        get _TintColorG() {
            return this.color.g;
        }
        set _TintColorG(value) {
            this.color.g = value;
        }
        get _TintColorB() {
            return this.color.b;
        }
        set _TintColorB(value) {
            this.color.b = value;
        }
        get _TintColorA() {
            return this.color.a;
        }
        set _TintColorA(value) {
            this.color.a = value;
        }
        get _MainTex_ST() {
            return this._shaderValues.getVector(ShurikenParticleMaterial.TILINGOFFSET);
        }
        set _MainTex_ST(value) {
            var tilOff = this._shaderValues.getVector(ShurikenParticleMaterial.TILINGOFFSET);
            tilOff.setValue(value.x, value.y, value.z, value.w);
            this.tilingOffset = tilOff;
        }
        get _MainTex_STX() {
            return this._shaderValues.getVector(ShurikenParticleMaterial.TILINGOFFSET).x;
        }
        set _MainTex_STX(x) {
            var tilOff = this._shaderValues.getVector(ShurikenParticleMaterial.TILINGOFFSET);
            tilOff.x = x;
            this.tilingOffset = tilOff;
        }
        get _MainTex_STY() {
            return this._shaderValues.getVector(ShurikenParticleMaterial.TILINGOFFSET).y;
        }
        set _MainTex_STY(y) {
            var tilOff = this._shaderValues.getVector(ShurikenParticleMaterial.TILINGOFFSET);
            tilOff.y = y;
            this.tilingOffset = tilOff;
        }
        get _MainTex_STZ() {
            return this._shaderValues.getVector(ShurikenParticleMaterial.TILINGOFFSET).z;
        }
        set _MainTex_STZ(z) {
            var tilOff = this._shaderValues.getVector(ShurikenParticleMaterial.TILINGOFFSET);
            tilOff.z = z;
            this.tilingOffset = tilOff;
        }
        get _MainTex_STW() {
            return this._shaderValues.getVector(ShurikenParticleMaterial.TILINGOFFSET).w;
        }
        set _MainTex_STW(w) {
            var tilOff = this._shaderValues.getVector(ShurikenParticleMaterial.TILINGOFFSET);
            tilOff.w = w;
            this.tilingOffset = tilOff;
        }
        get colorR() {
            return this._TintColorR;
        }
        set colorR(value) {
            this._TintColorR = value;
        }
        get colorG() {
            return this._TintColorG;
        }
        set colorG(value) {
            this._TintColorG = value;
        }
        get colorB() {
            return this._TintColorB;
        }
        set colorB(value) {
            this._TintColorB = value;
        }
        get colorA() {
            return this._TintColorA;
        }
        set colorA(value) {
            this._TintColorA = value;
        }
    }
    ShurikenParticleMaterial.RENDERMODE_ALPHABLENDED = 0;
    ShurikenParticleMaterial.RENDERMODE_ADDTIVE = 1;

    class ShurikenParticleRenderer extends Laya.BaseRender {
        get particleSystem() {
            return this._particleSystem;
        }
        get renderMode() {
            return this._renderMode;
        }
        set renderMode(value) {
            if (this._renderMode !== value) {
                var defineDatas = this._baseRenderNode.shaderData;
                switch (this._renderMode) {
                    case 0:
                        defineDatas.removeDefine(ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_RENDERMODE_BILLBOARD);
                        break;
                    case 1:
                        defineDatas.removeDefine(ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_RENDERMODE_STRETCHEDBILLBOARD);
                        break;
                    case 2:
                        defineDatas.removeDefine(ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_RENDERMODE_HORIZONTALBILLBOARD);
                        break;
                    case 3:
                        defineDatas.removeDefine(ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_RENDERMODE_VERTICALBILLBOARD);
                        break;
                    case 4:
                        defineDatas.removeDefine(ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_RENDERMODE_MESH);
                        break;
                }
                this._renderMode = value;
                switch (value) {
                    case 0:
                        defineDatas.addDefine(ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_RENDERMODE_BILLBOARD);
                        break;
                    case 1:
                        defineDatas.addDefine(ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_RENDERMODE_STRETCHEDBILLBOARD);
                        break;
                    case 2:
                        defineDatas.addDefine(ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_RENDERMODE_HORIZONTALBILLBOARD);
                        break;
                    case 3:
                        defineDatas.addDefine(ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_RENDERMODE_VERTICALBILLBOARD);
                        break;
                    case 4:
                        defineDatas.addDefine(ShuriKenParticle3DShaderDeclaration.SHADERDEFINE_RENDERMODE_MESH);
                        break;
                    default:
                        throw new Error("ShurikenParticleRender: unknown renderMode Value.");
                }
                var parSys = this._particleSystem;
                (parSys) && (parSys._initBufferDatas());
            }
        }
        get mesh() {
            return this._mesh;
        }
        set mesh(value) {
            if (this._mesh !== value) {
                (this._mesh) && (this._mesh._removeReference());
                this._mesh = value;
                (value) && (value._addReference());
                this._particleSystem._initBufferDatas();
            }
        }
        get pivot() {
            return this._pivot;
        }
        set pivot(value) {
            value.cloneTo(this._pivot);
        }
        constructor() {
            super();
            this._finalGravity = new Laya.Vector3();
            this._dragConstant = new Laya.Vector2();
            this._mesh = null;
            this._pivot = new Laya.Vector3(0, 0, 0);
            this.stretchedBillboardCameraSpeedScale = 0;
            this.stretchedBillboardSpeedScale = 0;
            this.stretchedBillboardLengthScale = 2;
            this.renderMode = 0;
            this._baseRenderNode.renderNodeType = Laya.BaseRenderType.ParticleRender;
        }
        _isMaterialVaild(value) {
            return value.checkType(Laya.ShaderFeatureType.Effect);
        }
        _getcommonUniformMap() {
            return ["Sprite3D", "ShurikenSprite3D"];
        }
        _onAdded() {
            super._onAdded();
            if (!Laya.LayaGL.renderEngine.getCapable(Laya.RenderCapable.DrawElement_Instance)) {
                this._particleSystem = new ShurikenParticleSystem(this);
            }
            else
                this._particleSystem = new ShurikenParticleInstanceSystem(this);
            var elements = this._renderElements;
            var element = elements[0] = new Laya.RenderElement();
            element.setTransform(this.owner._transform);
            element.render = this;
            element.setGeometry(this._particleSystem);
            element.material = ShurikenParticleMaterial.defaultMaterial;
            this._setRenderElements();
        }
        _onEnable() {
            super._onEnable();
            (this._particleSystem.playOnAwake && Laya.LayaEnv.isPlaying) && (this._particleSystem.play());
        }
        _onDisable() {
            super._onDisable();
            (this._particleSystem.isAlive) && (this._particleSystem.simulate(0, true));
        }
        _calculateBoundingBox() {
            var particleSystem = this._particleSystem;
            var bounds;
            if (particleSystem._useCustomBounds) {
                bounds = particleSystem.customBounds;
                bounds._tranform(this.owner.transform.worldMatrix, this._bounds);
            }
            else if (particleSystem._simulationSupported()) {
                particleSystem._generateBounds();
                bounds = particleSystem._bounds;
                bounds._tranform(this.owner.transform.worldMatrix, this._bounds);
                if (particleSystem.gravityModifier != 0) {
                    var max = this._bounds.getMax();
                    var min = this._bounds.getMin();
                    var gravityOffset = particleSystem._gravityOffset;
                    max.y -= gravityOffset.x;
                    min.y -= gravityOffset.y;
                    this._bounds.setMax(max);
                    this._bounds.setMin(min);
                }
            }
            else {
                var min = this._bounds.getMin();
                min.setValue(-Number.MAX_VALUE, -Number.MAX_VALUE, -Number.MAX_VALUE);
                this._bounds.setMin(min);
                var max = this._bounds.getMax();
                max.setValue(Number.MAX_VALUE, Number.MAX_VALUE, Number.MAX_VALUE);
                this._bounds.setMax(max);
            }
        }
        _needRender(boundFrustum, context) {
            if (!Laya.Stat.enableParticle)
                return false;
            if (boundFrustum) {
                if (boundFrustum.intersects(this.bounds)) {
                    if (this._particleSystem.isAlive)
                        return true;
                    else
                        return false;
                }
                else {
                    return false;
                }
            }
            else {
                return true;
            }
        }
        _renderUpdate(context) {
            var particleSystem = this._particleSystem;
            var sv = this._baseRenderNode.shaderData;
            var transform = this.owner.transform;
            switch (particleSystem.simulationSpace) {
                case 0:
                    break;
                case 1:
                    sv.setVector3(ShuriKenParticle3DShaderDeclaration.WORLDPOSITION, transform.position);
                    sv.setShaderData(ShuriKenParticle3DShaderDeclaration.WORLDROTATION, Laya.ShaderDataType.Vector4, transform.rotation);
                    break;
                default:
                    throw new Error("ShurikenParticleMaterial: SimulationSpace value is invalid.");
            }
            if (particleSystem.shape && particleSystem.shape.enable) {
                sv.setBool(ShuriKenParticle3DShaderDeclaration.SHAPE, true);
            }
            else {
                sv.setBool(ShuriKenParticle3DShaderDeclaration.SHAPE, false);
            }
            switch (particleSystem.scaleMode) {
                case 0:
                    var scale = transform.getWorldLossyScale();
                    sv.setVector3(ShuriKenParticle3DShaderDeclaration.POSITIONSCALE, scale);
                    sv.setVector3(ShuriKenParticle3DShaderDeclaration.SIZESCALE, scale);
                    break;
                case 1:
                    var localScale = transform.localScale;
                    sv.setVector3(ShuriKenParticle3DShaderDeclaration.POSITIONSCALE, localScale);
                    sv.setVector3(ShuriKenParticle3DShaderDeclaration.SIZESCALE, localScale);
                    break;
                case 2:
                    sv.setVector3(ShuriKenParticle3DShaderDeclaration.POSITIONSCALE, transform.getWorldLossyScale());
                    sv.setVector3(ShuriKenParticle3DShaderDeclaration.SIZESCALE, Laya.Vector3.ONE);
                    break;
            }
            switch (particleSystem.dragType) {
                case 0:
                    this._dragConstant.setValue(particleSystem.dragSpeedConstantMin, particleSystem.dragSpeedConstantMin);
                    sv.setVector2(ShuriKenParticle3DShaderDeclaration.DRAG, this._dragConstant);
                    break;
                case 2:
                    this._dragConstant.setValue(particleSystem.dragSpeedConstantMin, particleSystem.dragSpeedConstantMax);
                    sv.setVector2(ShuriKenParticle3DShaderDeclaration.DRAG, this._dragConstant);
                    break;
                default:
                    this._dragConstant.setValue(0, 0);
                    break;
            }
            Laya.Vector3.scale(ShurikenParticleRenderer.gravity, particleSystem.gravityModifier, this._finalGravity);
            sv.setVector3(ShuriKenParticle3DShaderDeclaration.GRAVITY, this._finalGravity);
            sv.setInt(ShuriKenParticle3DShaderDeclaration.SIMULATIONSPACE, particleSystem.simulationSpace);
            sv.setBool(ShuriKenParticle3DShaderDeclaration.THREEDSTARTROTATION, particleSystem.threeDStartRotation);
            sv.setInt(ShuriKenParticle3DShaderDeclaration.SCALINGMODE, particleSystem.scaleMode);
            sv.setNumber(ShuriKenParticle3DShaderDeclaration.STRETCHEDBILLBOARDLENGTHSCALE, this.stretchedBillboardLengthScale);
            sv.setNumber(ShuriKenParticle3DShaderDeclaration.STRETCHEDBILLBOARDSPEEDSCALE, this.stretchedBillboardSpeedScale);
            sv.setNumber(ShuriKenParticle3DShaderDeclaration.CURRENTTIME, particleSystem._currentTime);
            sv.setVector3(ShuriKenParticle3DShaderDeclaration.PIVOT, this._pivot);
        }
        renderUpdate(context) {
            this._renderElements.forEach(element => {
                element._renderElementOBJ.isRender = element._geometry._prepareRender(context);
                element._geometry._prepareRender(context);
                element._geometry._updateRenderParams(context);
            });
        }
        get bounds() {
            if (this.boundsChange) {
                this._calculateBoundingBox();
                this.boundsChange = false;
            }
            return this._bounds;
        }
        _cloneTo(dest) {
            this._particleSystem.cloneTo(dest._particleSystem);
            dest.sharedMaterial = this.sharedMaterial;
            dest.renderMode = this.renderMode;
            dest.mesh = this.mesh;
            this._pivot.cloneTo(dest._pivot);
            dest.stretchedBillboardCameraSpeedScale = this.stretchedBillboardCameraSpeedScale;
            dest.stretchedBillboardSpeedScale = this.stretchedBillboardSpeedScale;
            dest.stretchedBillboardLengthScale = this.stretchedBillboardLengthScale;
            dest.sortingFudge = this.sortingFudge;
        }
        _onDestroy() {
            (this._mesh) && (this._mesh._removeReference(), this._mesh = null);
            this._particleSystem.destroy();
            this._particleSystem = null;
            super._onDestroy();
        }
        _statAdd() {
            super._statAdd();
            Laya.LayaGL.statAgent.recordCountData(Laya.StatElement.C_ShurikenParticleRenderCount, 1);
        }
        _statRemove() {
            super._statRemove();
            Laya.LayaGL.statAgent.recordCountData(Laya.StatElement.C_ShurikenParticleRenderCount, -1);
        }
    }
    ShurikenParticleRenderer.gravity = new Laya.Vector3(0, -9.81, 0);
    Laya.Laya.addInitCallback(() => {
        ParticleShuriKenShaderInit.init();
        VertexShurikenParticleBillboard.__init__();
        VertexShurikenParticleMesh.__init__();
        ShuriKenParticle3DShaderDeclaration.__init__();
        ShuriKenParticle3D.__init__();
        ShurikenParticleMaterial.__initDefine__();
    });

    class ShuriKenParticle3D extends Laya.RenderableSprite3D {
        get particleSystem() {
            return this._particleSystem;
        }
        get particleRenderer() {
            return this._render;
        }
        constructor() {
            super(null);
            this._render = this.addComponent(ShurikenParticleRenderer);
            this._particleSystem = this._render._particleSystem;
        }
        destroy(destroyChild = true) {
            if (this._destroyed)
                return;
            super.destroy(destroyChild);
        }
    }

    let c = Laya.ClassUtils.regClass;
    c("ShurikenParticleMaterial", ShurikenParticleMaterial);
    c("ShuriKenParticle3D", ShuriKenParticle3D);
    c("ShurikenParticleRenderer", ShurikenParticleRenderer);
    c("ShurikenParticleSystem", ShurikenParticleSystem);
    c("Burst", Burst);
    c("Emission", Emission);
    c("BaseShape", BaseShape);
    c("BoxShape", BoxShape);
    c("CircleShape", CircleShape);
    c("ConeShape", ConeShape);
    c("HemisphereShape", HemisphereShape);
    c("SphereShape", SphereShape);
    c("FrameOverTime", FrameOverTime);
    c("GradientAngularVelocity", GradientAngularVelocity);
    c("GradientColor", GradientColor);
    c("GradientDataInt", GradientDataInt);
    c("GradientSize", GradientSize);
    c("GradientVelocity", GradientVelocity);
    c("StartFrame", StartFrame);
    c("TextureSheetAnimation", TextureSheetAnimation);
    c("ColorOverLifetime", ColorOverLifetime);
    c("RotationOverLifetime", RotationOverLifetime);
    c("SizeOverLifetime", SizeOverLifetime);
    c("VelocityOverLifetime", VelocityOverLifetime);

    class GradientDataVector2 {
        get gradientCount() {
            return this._currentLength / 3;
        }
        constructor() {
            this._currentLength = 0;
            this._elements = new Float32Array(12);
        }
        add(key, value) {
            if (this._currentLength < 8) {
                if ((this._currentLength === 6) && ((key !== 1))) {
                    key = 1;
                    console.log("GradientDataVector2 warning:the forth key is  be force set to 1.");
                }
                this._elements[this._currentLength++] = key;
                this._elements[this._currentLength++] = value.x;
                this._elements[this._currentLength++] = value.y;
            }
            else {
                console.log("GradientDataVector2 warning:data count must lessEqual than 4");
            }
        }
        cloneTo(destObject) {
            destObject._currentLength = this._currentLength;
            var destElements = destObject._elements;
            for (var i = 0, n = this._elements.length; i < n; i++) {
                destElements[i] = this._elements[i];
            }
        }
        clone() {
            var destGradientDataVector2 = new GradientDataVector2();
            this.cloneTo(destGradientDataVector2);
            return destGradientDataVector2;
        }
    }

    exports.BaseShape = BaseShape;
    exports.BoxShape = BoxShape;
    exports.Burst = Burst;
    exports.CircleShape = CircleShape;
    exports.ColorOverLifetime = ColorOverLifetime;
    exports.ConeShape = ConeShape;
    exports.Emission = Emission;
    exports.FrameOverTime = FrameOverTime;
    exports.GradientAngularVelocity = GradientAngularVelocity;
    exports.GradientColor = GradientColor;
    exports.GradientDataInt = GradientDataInt;
    exports.GradientDataVector2 = GradientDataVector2;
    exports.GradientSize = GradientSize;
    exports.GradientVelocity = GradientVelocity;
    exports.HemisphereShape = HemisphereShape;
    exports.ParticleShuriKenShaderInit = ParticleShuriKenShaderInit;
    exports.RotationOverLifetime = RotationOverLifetime;
    exports.ShapeUtils = ShapeUtils;
    exports.ShuriKenParticle3D = ShuriKenParticle3D;
    exports.ShuriKenParticle3DShaderDeclaration = ShuriKenParticle3DShaderDeclaration;
    exports.ShurikenParticleData = ShurikenParticleData;
    exports.ShurikenParticleInstanceSystem = ShurikenParticleInstanceSystem;
    exports.ShurikenParticleMaterial = ShurikenParticleMaterial;
    exports.ShurikenParticleRenderer = ShurikenParticleRenderer;
    exports.ShurikenParticleSystem = ShurikenParticleSystem;
    exports.SizeOverLifetime = SizeOverLifetime;
    exports.SphereShape = SphereShape;
    exports.StartFrame = StartFrame;
    exports.TextureSheetAnimation = TextureSheetAnimation;
    exports.VelocityOverLifetime = VelocityOverLifetime;
    exports.VertexShuriKenParticle = VertexShuriKenParticle;
    exports.VertexShurikenParticleBillboard = VertexShurikenParticleBillboard;
    exports.VertexShurikenParticleMesh = VertexShurikenParticleMesh;

})(window.Laya = window.Laya || {}, Laya);
//# sourceMappingURL=laya.particle3D.js.map
