(function (exports, Laya) {
    'use strict';

    exports.TrailTextureMode = void 0;
    (function (TrailTextureMode) {
        TrailTextureMode[TrailTextureMode["Stretch"] = 0] = "Stretch";
        TrailTextureMode[TrailTextureMode["Tile"] = 1] = "Tile";
    })(exports.TrailTextureMode || (exports.TrailTextureMode = {}));

    class VertexTrail {
        static get vertexDeclaration1() {
            return VertexTrail._vertexDeclaration1;
        }
        static get vertexDeclaration2() {
            return VertexTrail._vertexDeclaration2;
        }
        get vertexDeclaration() {
            return VertexTrail._vertexDeclaration1;
        }
        static __init__() {
            VertexTrail._vertexDeclaration1 = new Laya.VertexDeclaration(32, [new Laya.VertexElement(0, Laya.VertexElementFormat.Vector3, VertexTrail.TRAIL_POSITION0),
                new Laya.VertexElement(12, Laya.VertexElementFormat.Vector3, VertexTrail.TRAIL_OFFSETVECTOR),
                new Laya.VertexElement(24, Laya.VertexElementFormat.Single, VertexTrail.TRAIL_TIME0),
                new Laya.VertexElement(28, Laya.VertexElementFormat.Single, VertexTrail.TRAIL_TEXTURECOORDINATE0Y)]);
            VertexTrail._vertexDeclaration2 = new Laya.VertexDeclaration(20, [new Laya.VertexElement(0, Laya.VertexElementFormat.Single, VertexTrail.TRAIL_TEXTURECOORDINATE0X),
                new Laya.VertexElement(4, Laya.VertexElementFormat.Color, VertexTrail.TRAIL_COLOR)]);
        }
    }
    VertexTrail.TRAIL_POSITION0 = 0;
    VertexTrail.TRAIL_OFFSETVECTOR = 1;
    VertexTrail.TRAIL_TIME0 = 2;
    VertexTrail.TRAIL_TEXTURECOORDINATE0Y = 3;
    VertexTrail.TRAIL_TEXTURECOORDINATE0X = 4;
    VertexTrail.TRAIL_COLOR = 5;

    class TrailGeometry {
        constructor() {
            this._floatCountPerVertices1 = 8;
            this._floatCountPerVertices2 = 5;
            this._increaseSegementCount = 16;
            this._needAddFirstVertex = false;
            this._isTempEndVertex = false;
            this._vertices1 = null;
            this._vertices2 = null;
            this._lastFixedVertexPosition = new Laya.Vector3();
            this.tmpColor = new Laya.Color();
            this._totalLength = 0;
            this._activeIndex = 0;
            this._endIndex = 0;
            this._disappearBoundsMode = false;
            this._geometryElementOBj = Laya.LayaGL.renderDeviceFactory.createRenderGeometryElement(Laya.MeshTopology.TriangleStrip, Laya.DrawType.DrawArray);
            this._bufferState = Laya.LayaGL.renderDeviceFactory.createBufferState();
            this._geometryElementOBj.bufferState = this._bufferState;
            this._segementCount = this._increaseSegementCount;
            this._resizeData(this._segementCount);
        }
        _resizeData(segementCount) {
            this._subBirthTime = new Float32Array(segementCount);
            this._subDistance = new Float64Array(segementCount);
            var vertexCount = segementCount * 2;
            var vertexDeclaration1 = VertexTrail.vertexDeclaration1;
            var vertexDeclaration2 = VertexTrail.vertexDeclaration2;
            var vertexBuffers = [];
            var vertexbuffer1Size = vertexCount * vertexDeclaration1.vertexStride;
            var vertexbuffer2Size = vertexCount * vertexDeclaration2.vertexStride;
            this._vertices1 = new Float32Array(vertexCount * this._floatCountPerVertices1);
            this._vertices2 = new Float32Array(vertexCount * this._floatCountPerVertices2);
            this._vertexBuffer1 = Laya.LayaGL.renderDeviceFactory.createVertexBuffer(Laya.BufferUsage.Dynamic);
            this._vertexBuffer1.vertexDeclaration = vertexDeclaration1;
            this._vertexBuffer1.setDataLength(vertexbuffer1Size);
            this._vertexBuffer1.setData(this._vertices1.buffer, 0, 0, vertexbuffer1Size);
            this._vertexBuffer2 = Laya.LayaGL.renderDeviceFactory.createVertexBuffer(Laya.BufferUsage.Dynamic);
            this._vertexBuffer2.vertexDeclaration = vertexDeclaration2;
            this._vertexBuffer2.setDataLength(vertexbuffer2Size);
            this._vertexBuffer2.setData(this._vertices2.buffer, 0, 0, vertexbuffer2Size);
            vertexBuffers.push(this._vertexBuffer1);
            vertexBuffers.push(this._vertexBuffer2);
            this._bufferState.applyState(vertexBuffers, null);
        }
        _resetData() {
            var count = this._endIndex - this._activeIndex;
            var oldVertices1 = new Float32Array(this._vertices1.buffer, this._floatCountPerVertices1 * 2 * this._activeIndex * 4, this._floatCountPerVertices1 * 2 * count);
            var oldVertices2 = new Float32Array(this._vertices2.buffer, this._floatCountPerVertices2 * 2 * this._activeIndex * 4, this._floatCountPerVertices2 * 2 * count);
            var oldSubDistance = new Float64Array(this._subDistance.buffer, this._activeIndex * 8, count);
            var oldSubBirthTime = new Float32Array(this._subBirthTime.buffer, this._activeIndex * 4, count);
            if (count === this._segementCount) {
                this._vertexBuffer1.destroy();
                this._vertexBuffer2.destroy();
                this._segementCount += this._increaseSegementCount;
                this._resizeData(this._segementCount);
            }
            this._vertices1.set(oldVertices1, 0);
            this._vertices2.set(oldVertices2, 0);
            this._subDistance.set(oldSubDistance, 0);
            this._subBirthTime.set(oldSubBirthTime, 0);
            this._endIndex = count;
            this._activeIndex = 0;
            this._vertexBuffer1.setData(this._vertices1.buffer, 0, this._floatCountPerVertices1 * 2 * this._activeIndex * 4, this._floatCountPerVertices1 * 2 * count * 4);
            this._vertexBuffer2.setData(this._vertices2.buffer, 0, this._floatCountPerVertices2 * 2 * this._activeIndex * 4, this._floatCountPerVertices2 * 2 * count * 4);
        }
        _addTrailByFirstPosition(position, curtime) {
            (this._endIndex === this._segementCount) && (this._resetData());
            this._subDistance[this._endIndex] = 0;
            this._subBirthTime[this._endIndex] = curtime;
            this._endIndex++;
            position.cloneTo(this._lastFixedVertexPosition);
            this._needAddFirstVertex = true;
        }
        _addTrailByNextPosition(position, curtime, minVertexDistance, pointAtoBVector3, delLength) {
            var tempEndIndex;
            var offset;
            if (this._needAddFirstVertex) {
                this._updateVerticesByPositionData(position, pointAtoBVector3, this._endIndex - 1, curtime);
                this._needAddFirstVertex = false;
            }
            if (delLength - minVertexDistance >= TrailGeometry.zeroTolerance) {
                if (this._isTempEndVertex) {
                    tempEndIndex = this._endIndex - 1;
                    offset = delLength - this._subDistance[tempEndIndex];
                    this._updateVerticesByPosition(position, pointAtoBVector3, delLength, tempEndIndex, curtime);
                    this._totalLength += offset;
                }
                else {
                    (this._endIndex === this._segementCount) && (this._resetData());
                    this._updateVerticesByPosition(position, pointAtoBVector3, delLength, this._endIndex, curtime);
                    this._totalLength += delLength;
                    this._endIndex++;
                }
                position.cloneTo(this._lastFixedVertexPosition);
                this._isTempEndVertex = false;
            }
            else {
                if (this._isTempEndVertex) {
                    tempEndIndex = this._endIndex - 1;
                    offset = delLength - this._subDistance[tempEndIndex];
                    this._updateVerticesByPosition(position, pointAtoBVector3, delLength, tempEndIndex, curtime);
                    this._totalLength += offset;
                }
                else {
                    (this._endIndex === this._segementCount) && (this._resetData());
                    this._updateVerticesByPosition(position, pointAtoBVector3, delLength, this._endIndex, curtime);
                    this._totalLength += delLength;
                    this._endIndex++;
                }
                this._isTempEndVertex = true;
            }
        }
        _updateVerticesByPositionData(position, pointAtoBVector3, index, curtime) {
            var vertexOffset = this._floatCountPerVertices1 * 2 * index;
            this._vertices1[vertexOffset] = position.x;
            this._vertices1[vertexOffset + 1] = position.y;
            this._vertices1[vertexOffset + 2] = position.z;
            this._vertices1[vertexOffset + 3] = -pointAtoBVector3.x;
            this._vertices1[vertexOffset + 4] = -pointAtoBVector3.y;
            this._vertices1[vertexOffset + 5] = -pointAtoBVector3.z;
            this._vertices1[vertexOffset + 6] = curtime;
            this._vertices1[vertexOffset + 7] = 1.0;
            this._vertices1[vertexOffset + 8] = position.x;
            this._vertices1[vertexOffset + 9] = position.y;
            this._vertices1[vertexOffset + 10] = position.z;
            this._vertices1[vertexOffset + 11] = pointAtoBVector3.x;
            this._vertices1[vertexOffset + 12] = pointAtoBVector3.y;
            this._vertices1[vertexOffset + 13] = pointAtoBVector3.z;
            this._vertices1[vertexOffset + 14] = curtime;
            this._vertices1[vertexOffset + 15] = 0.0;
            this._disappearBoundsMode = true;
            var floatCount = this._floatCountPerVertices1 * 2;
            this._vertexBuffer1.setData(this._vertices1.buffer, vertexOffset * 4, vertexOffset * 4, floatCount * 4);
        }
        _updateVerticesByPosition(position, pointAtoBVector3, delDistance, index, curtime) {
            this._updateVerticesByPositionData(position, pointAtoBVector3, index, curtime);
            this._subDistance[index] = delDistance;
            this._subBirthTime[index] = curtime;
        }
        _updateVertexBufferUV(colorGradient, textureMode, tileUnit = 1) {
            var vertexCount = this._endIndex;
            var curLength = 0;
            var gradient = colorGradient;
            var startAlphaIndex = gradient.colorAlphaKeysCount - 1;
            var startColorIndex = gradient.colorRGBKeysCount - 1;
            var totalLength = this._totalLength;
            var stride = this._floatCountPerVertices2 * 2;
            for (var i = this._activeIndex; i < vertexCount; i++) {
                (i !== this._activeIndex) && (curLength += this._subDistance[i]);
                var uvX;
                var lerpFactor;
                if (textureMode == exports.TrailTextureMode.Stretch) {
                    uvX = 1.0 - curLength / totalLength;
                    lerpFactor = uvX;
                }
                else {
                    lerpFactor = 1.0 - curLength / totalLength;
                    uvX = 1.0 - (totalLength - curLength) / tileUnit;
                }
                startColorIndex = gradient.evaluateColorRGB(lerpFactor, this.tmpColor, startColorIndex, true);
                startAlphaIndex = gradient.evaluateColorAlpha(lerpFactor, this.tmpColor, startAlphaIndex, true);
                var index = i * stride;
                this._vertices2[index + 0] = uvX;
                this._vertices2[index + 1] = this.tmpColor.r;
                this._vertices2[index + 2] = this.tmpColor.g;
                this._vertices2[index + 3] = this.tmpColor.b;
                this._vertices2[index + 4] = this.tmpColor.a;
                this._vertices2[index + 5] = uvX;
                this._vertices2[index + 6] = this.tmpColor.r;
                this._vertices2[index + 7] = this.tmpColor.g;
                this._vertices2[index + 8] = this.tmpColor.b;
                this._vertices2[index + 9] = this.tmpColor.a;
            }
            var offset = this._activeIndex * stride;
            this._vertexBuffer2.setData(this._vertices2.buffer, offset * 4, offset * 4, (vertexCount * stride - offset) * 4);
        }
        _updateDisappear(curtime, lifetime) {
            var count = this._endIndex;
            for (var i = this._activeIndex; i < count; i++) {
                if (curtime - this._subBirthTime[i] >= lifetime + TrailGeometry.zeroTolerance) {
                    var nextIndex = i + 1;
                    if (nextIndex !== count)
                        this._totalLength -= this._subDistance[nextIndex];
                    if (this._isTempEndVertex && (nextIndex === count - 1)) {
                        var fixedPos = this._lastFixedVertexPosition;
                        fixedPos.x = this._vertices1[0];
                        fixedPos.y = this._vertices1[1];
                        fixedPos.z = this._vertices1[2];
                        this._isTempEndVertex = false;
                    }
                    this._activeIndex++;
                    this._disappearBoundsMode = true;
                }
                else {
                    break;
                }
            }
        }
        _updateRenderParams() {
            this._geometryElementOBj.clearRenderParams();
            var start = this._activeIndex * 2;
            var count = this._endIndex * 2 - start;
            this._geometryElementOBj.setDrawArrayParams(start, count);
        }
        destroy() {
            this._geometryElementOBj.destroy();
            this._vertexBuffer1.destroy();
            this._vertexBuffer2.destroy();
            this._bufferState.destroy();
            this._bufferState = null;
            this._vertices1 = null;
            this._vertexBuffer1 = null;
            this._vertices2 = null;
            this._vertexBuffer2 = null;
            this._subBirthTime = null;
            this._subDistance = null;
            this._lastFixedVertexPosition = null;
            this._disappearBoundsMode = false;
        }
        clear() {
            this._activeIndex = 0;
            this._endIndex = 0;
            this._disappearBoundsMode = false;
            this._subBirthTime.fill(0);
            this._subDistance.fill(0);
            this._segementCount = 0;
            this._isTempEndVertex = false;
            this._needAddFirstVertex = false;
            this._lastFixedVertexPosition.setValue(0, 0, 0);
            this._totalLength = 0;
        }
    }
    TrailGeometry.zeroTolerance = 1e-6;
    TrailGeometry._tempVector33 = new Laya.Vector3();
    TrailGeometry._tempVector34 = new Laya.Vector3();
    TrailGeometry._tempVector35 = new Laya.Vector3();
    TrailGeometry._tempVector36 = new Laya.Vector3();

    var TrailVertexUtilGLSL = "uniform float u_CurTime;uniform float u_LifeTime;uniform vec4 u_WidthCurve[10];uniform int u_WidthCurveKeyLength;varying vec2 v_Texcoord0;varying vec4 v_Color;float hermiteInterpolate(float t,float outTangent,float inTangent,float duration,float value1,float value2){float t2=t*t;float t3=t2*t;float a=2.0*t3-3.0*t2+1.0;float b=t3-2.0*t2+t;float c=t3-t2;float d=-2.0*t3+3.0*t2;return a*value1+b*outTangent*duration+c*inTangent*duration+d*value2;}float getCurWidth(in float normalizeTime){float width;if(normalizeTime==0.0){width=u_WidthCurve[0].w;}else if(normalizeTime>=1.0){width=u_WidthCurve[u_WidthCurveKeyLength-1].w;}else{for(int i=0;i<10;i++){if(normalizeTime==u_WidthCurve[i].x){width=u_WidthCurve[i].w;break;}vec4 lastFrame=u_WidthCurve[i];vec4 nextFrame=u_WidthCurve[i+1];if(normalizeTime>lastFrame.x&&normalizeTime<nextFrame.x){float duration=nextFrame.x-lastFrame.x;float t=(normalizeTime-lastFrame.x)/duration;float outTangent=lastFrame.z;float inTangent=nextFrame.y;float value1=lastFrame.w;float value2=nextFrame.w;width=hermiteInterpolate(t,outTangent,inTangent,duration,value1,value2);break;}}}return width;}";

    class TrailShaderCommon {
        static init() {
            if (this.inited)
                return;
            TrailShaderCommon.CURTIME = Laya.Shader3D.propertyNameToID("u_CurTime");
            TrailShaderCommon.LIFETIME = Laya.Shader3D.propertyNameToID("u_LifeTime");
            TrailShaderCommon.WIDTHCURVE = Laya.Shader3D.propertyNameToID("u_WidthCurve");
            TrailShaderCommon.WIDTHCURVEKEYLENGTH = Laya.Shader3D.propertyNameToID("u_WidthCurveKeyLength");
            const spriteParms = Laya.LayaGL.renderDeviceFactory.createGlobalUniformMap("TrailRender");
            spriteParms.addShaderUniform(TrailShaderCommon.CURTIME, "u_CurTime", Laya.ShaderDataType.Float);
            spriteParms.addShaderUniform(TrailShaderCommon.LIFETIME, "u_LifeTime", Laya.ShaderDataType.Float);
            spriteParms.addShaderUniformArray(TrailShaderCommon.WIDTHCURVE, "u_WidthCurve", Laya.ShaderDataType.Vector4, 10);
            spriteParms.addShaderUniform(TrailShaderCommon.WIDTHCURVEKEYLENGTH, "u_WidthCurveKeyLength", Laya.ShaderDataType.Int);
            TrailShaderCommon.attributeMap = {
                'a_position': [VertexTrail.TRAIL_POSITION0, Laya.ShaderDataType.Vector4],
                'a_OffsetVector': [VertexTrail.TRAIL_OFFSETVECTOR, Laya.ShaderDataType.Vector3],
                'a_Texcoord0X': [VertexTrail.TRAIL_TEXTURECOORDINATE0X, Laya.ShaderDataType.Float],
                'a_Texcoord0Y': [VertexTrail.TRAIL_TEXTURECOORDINATE0Y, Laya.ShaderDataType.Float],
                'a_BirthTime': [VertexTrail.TRAIL_TIME0, Laya.ShaderDataType.Float],
                'a_Color': [VertexTrail.TRAIL_COLOR, Laya.ShaderDataType.Vector4],
            };
            TrailShaderCommon.uniformMap = {
                "u_TilingOffset": Laya.ShaderDataType.Vector4,
                "u_MainTexture": Laya.ShaderDataType.Texture2D,
                "u_MainColor": Laya.ShaderDataType.Color,
            };
            TrailShaderCommon.defaultValue = {
                "u_MainColor": Laya.Color.WHITE,
                "u_TilingOffset": new Laya.Vector4(1, 1, 0, 0),
            };
            Laya.Shader3D.addInclude("TrailVertexUtil.glsl", TrailVertexUtilGLSL);
            VertexTrail.__init__();
            this.inited = true;
        }
    }
    TrailShaderCommon.inited = false;

    class TrailBaseFilter {
        get time() {
            return this._time;
        }
        set time(value) {
            this._time = value;
            this._nodeShaderData.setNumber(TrailShaderCommon.LIFETIME, value);
        }
        get minVertexDistance() {
            return this._minVertexDistance;
        }
        set minVertexDistance(value) {
            this._minVertexDistance = value;
        }
        get widthMultiplier() {
            return this._widthMultiplier;
        }
        set widthMultiplier(value) {
            this._widthMultiplier = value;
        }
        get widthCurve() {
            return this._widthCurve;
        }
        set widthCurve(value) {
            this._widthCurve = value;
            var widthCurveFloatArray = new Float32Array(value.length * 4);
            var i, j, index = 0;
            for (i = 0, j = value.length; i < j; i++) {
                widthCurveFloatArray[index++] = value[i].time;
                widthCurveFloatArray[index++] = value[i].inTangent;
                widthCurveFloatArray[index++] = value[i].outTangent;
                widthCurveFloatArray[index++] = value[i].value;
            }
            this._nodeShaderData.setBuffer(TrailShaderCommon.WIDTHCURVE, widthCurveFloatArray);
            this._nodeShaderData.setInt(TrailShaderCommon.WIDTHCURVEKEYLENGTH, value.length);
        }
        get colorGradient() {
            return this._colorGradient;
        }
        set colorGradient(value) {
            this._colorGradient = value;
        }
        get textureMode() {
            return this._textureMode;
        }
        set textureMode(value) {
            this._textureMode = value;
        }
        constructor(nodeShaderData) {
            this._textureMode = exports.TrailTextureMode.Stretch;
            this._lastPosition = new Laya.Vector3();
            this._curtime = 0;
            this._nodeShaderData = nodeShaderData;
            this._initDefaultData();
            this._trialGeometry = new TrailGeometry();
        }
        _isRender() {
            return this._trialGeometry._endIndex - this._trialGeometry._activeIndex > 1;
        }
        _initDefaultData() {
            this.time = 5.0;
            this.minVertexDistance = 0.1;
            this.widthMultiplier = 1;
            this.textureMode = exports.TrailTextureMode.Stretch;
            var widthKeyFrames = [];
            var widthKeyFrame1 = new Laya.FloatKeyframe();
            widthKeyFrame1.time = 0;
            widthKeyFrame1.inTangent = 0;
            widthKeyFrame1.outTangent = 0;
            widthKeyFrame1.value = 1;
            widthKeyFrames.push(widthKeyFrame1);
            var widthKeyFrame2 = new Laya.FloatKeyframe();
            widthKeyFrame2.time = 1;
            widthKeyFrame2.inTangent = 0;
            widthKeyFrame2.outTangent = 0;
            widthKeyFrame2.value = 1;
            widthKeyFrames.push(widthKeyFrame2);
            this.widthCurve = widthKeyFrames;
            var gradient = new Laya.Gradient();
            gradient.mode = Laya.GradientMode.Blend;
            gradient.addColorRGB(0, Laya.Color.WHITE);
            gradient.addColorRGB(1, Laya.Color.WHITE);
            gradient.addColorAlpha(0, 1);
            gradient.addColorAlpha(1, 1);
            this.colorGradient = gradient;
        }
        destroy() {
            this._trialGeometry.destroy();
            this._trialGeometry = null;
            this._widthCurve = null;
            this._colorGradient = null;
        }
        clear() {
            this._trialGeometry.clear();
            this._lastPosition.setValue(0, 0, 0);
            this._curtime = 0;
        }
    }

    exports.TrailBaseFilter = TrailBaseFilter;
    exports.TrailGeometry = TrailGeometry;
    exports.TrailShaderCommon = TrailShaderCommon;
    exports.VertexTrail = VertexTrail;

})(window.Laya = window.Laya || {}, Laya);
//# sourceMappingURL=laya.trailCommon.js.map
