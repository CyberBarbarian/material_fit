Shader3D Start
{
    type: Shader3D,
    name: "Custom/FishStandar_Low",
    enableInstancing: true,
    supportReflectionProbe: true,
    shaderType: D3,
    uniformMap: {
        u_Color: { type: Color, default: [1, 1, 1, 1] },
        u_MainTex: { type: Texture2D, default: "white" },
        u_MainTex_ST: { type: Vector4, default: [1, 1, 0, 0] },
        u_TexPower: { type: Float, default: 1.0, range: [0.1, 3.0] },
        u_GammaPower: { type: Float, default: 1.0, range: [0.0001, 3.0] },

        u_SpeTex: { type: Texture2D, default: "white" },
        u_SpeTex_ST: { type: Vector4, default: [1, 1, 0, 0] },

        u_LMap: { type: Texture2D, default: "white", alias: "R:Emiss G:Sky B:AO A:Rim" },
        //u_LMap_ST: { type: Vector4, default: [1, 1, 0, 0] },

        u_NormalTex: { type: Texture2D, default: "bump" },
        u_NormalTex_ST: { type: Vector4, default: [1, 1, 0, 0] },
        u_NormalScale: { type: Float, default: 1, range: [0.0, 1.2] },

        u_AoPower: { type: Float, default: 0.1, range: [0.0, 1.0] },

        u_EmissionTex: { type: Texture2D, default: "white" },
        u_EmissionTex_ST: { type: Vector4, default: [1, 1, 0, 0] },
        u_EmissionPow: { type: Float, default: 0.0 },

        u_CustomReflectTex: { type: TextureCube, default: "black" },
        u_ReflectColor: { type: Color, default: [0, 0, 0, 1] },
        u_IndirectStrength: { type: Float, default: 1 },
        u_SkyRotateX: { type: Float, default: 0, range: [0.0, 360.0] },
        u_SkyRotateY: { type: Float, default: 0, range: [0.0, 360.0] },
        u_SkyRotateZ: { type: Float, default: 0, range: [0.0, 360.0] },

        u_ShadowSmoothness: { type: Float, default: 0.1, range: [0.0, 1.0] },
        u_ShadowColor1: { type: Color, default: [0.7, 0.7, 0.7, 1] },
        u_ShadowThreshold1: { type: Float, default: 0.3, range: [0.0, 1.0] },
        u_ShadowColor2: { type: Color, default: [0.5, 0.5, 0.5, 1], hidden: "!data.USE_SECOND_LEVELS" },
        u_ShadowThreshold2: { type: Float, default: 0.4, range: [0.0, 1.0], hidden: "!data.USE_SECOND_LEVELS" },

        u_SpecularColor: { type: Color, default: [0.9, 0.9, 0.9, 1] },
        u_SpecularIntensity: { type: Float, default: 1.0, range: [0.0, 10.0] },
        u_SpecularPower: { type: Float, default: 8, range: [8, 200] },
        u_SpecularThreshold: { type: Float, default: 0.7, range: [0.0, 1.0] },
        u_SpecularSmoothness: { type: Float, default: 0.4, range: [0.0, 1.0] },
        u_SpeOffet: { type: Vector4, default: [0, 0, 0, 0] },

        u_RimColor: { type: Color, default: [1, 0.9, 0.8, 1] },
        u_RimIntensity: { type: Float, default: 0, range: [0, 10] },
        u_RimWidth: { type: Float, default: 0, range: [0, 10] },
        u_RimOffet: { type: Vector4, default: [0, 0, 0, 0] },

        u_LightRotateX: { type: Float, default: 0, range: [0.0, 360.0] },
        u_LightRotateY: { type: Float, default: 0, range: [0.0, 360.0] },
        u_LightRotateZ: { type: Float, default: 0, range: [0.0, 360.0] },

        u_HueShift: { type: Float, default: 0, range: [0.0, 1.0] },
        u_Saturation: { type: Float, default: 1, range: [0.0, 2.0] },
        u_Contrast: { type: Float, default: 1, range: [0.0, 2.0] },

        u_AlphaTestValue: { type: Float, default: 0.5, range: [0.0, 1.0] }
    },
    defines: {
       // UV: { type: bool, default: true },
        NORMALMAP: { type: bool, default: false },
        NORMALMAP_Y_INVERT: { type: bool, default: true },
       // DIRECTIONLIGHT: { type: bool, default: true, position: "before u_LightRotateX" },
        USE_SECOND_LEVELS: { type: bool, default: false, position: "before u_ShadowColor2" },
        RIMSMOOTHNESS: { type: bool, default: false },
        ALPHATEST: { type: bool, default: false }
    },
    shaderPass: [
        {
            pipeline: Forward,
            VS: FishLowVS,
            FS: FishLowFS
        }
    ]
}
Shader3D End

GLSL Start
#defineGLSL FishLowVS
    #include "Sprite3DVertex.glsl";
    #include "VertexCommon.glsl";
    #include "Scene.glsl";
    #include "Camera.glsl";

    // 声明切线属性
    attribute vec4 a_Tangent;

    varying vec3 v_PositionWS;
    varying vec3 v_NormalWS;
    varying vec2 v_UV;
    varying vec3 v_TangentWS;
    varying vec3 v_BinormalWS;

    void main()
    {
        Vertex vertex;
        getVertexParams(vertex);

        mat4 worldMat = getWorldMatrix();
        vec4 posWS = worldMat * vec4(vertex.positionOS, 1.0);
        v_PositionWS = posWS.xyz;

        mat3 normalMat = mat3(worldMat);
        v_NormalWS = normalize(normalMat * vertex.normalOS);

        //#ifdef UV
            v_UV = vertex.texCoord0;
       // #else
        //    v_UV = vec2(0.0);
       // #endif

        // 使用引擎的切线数据，如果没有则自动生成
        vec3 tangentOS = a_Tangent.xyz;
        float tangentW = a_Tangent.w;

        // 检查切线是否有效
        if (dot(tangentOS, tangentOS) < 0.0001) {
            // 生成与法线垂直的切线
            vec3 normalOS = vertex.normalOS;
            if (abs(normalOS.x) > 0.9) {
                tangentOS = cross(normalOS, vec3(0.0, 1.0, 0.0));
            } else {
                tangentOS = cross(normalOS, vec3(1.0, 0.0, 0.0));
            }
            tangentW = 1.0;
        }

        v_TangentWS = normalize(normalMat * tangentOS);
        v_BinormalWS = cross(v_NormalWS, v_TangentWS) * tangentW;

        gl_Position = getPositionCS(v_PositionWS);
        gl_Position = remapPositionZ(gl_Position);

    #ifdef FOG
        FogHandle(gl_Position.z);
    #endif
    }
#endGLSL

#defineGLSL FishLowFS
    #include "Color.glsl";
    #include "Camera.glsl";
    #include "Scene.glsl";
    #include "Lighting.glsl";

    varying vec3 v_PositionWS;
    varying vec3 v_NormalWS;
    varying vec2 v_UV;
    varying vec3 v_TangentWS;
    varying vec3 v_BinormalWS;

    vec3 safeNormalize(vec3 v)
    {
        float len = length(v);
        if (len < 1e-4) return vec3(0.0, 1.0, 0.0);
        return v / len;
    }

    float calculateRamp(float threshold, float value, float smoothness)
    {
        float center = clamp(1.0 - threshold, 0.0, 1.0);
        float minValue = clamp(center - smoothness, 0.0, 1.0);
        float maxValue = clamp(center + smoothness, 0.0, 1.0);
        return smoothstep(minValue, maxValue, value);
    }

    vec3 RGBtoHSV(vec3 c)
    {
        vec4 K = vec4(0.0, -1.0 / 3.0, 2.0 / 3.0, -1.0);
        vec4 p = mix(vec4(c.bg, K.wz), vec4(c.gb, K.xy), step(c.b, c.g));
        vec4 q = mix(vec4(p.xyw, c.r), vec4(c.r, p.yzx), step(p.x, c.r));
        float d = q.x - min(q.w, q.y);
        float e = 1.0e-10;
        return vec3(abs(q.z + (q.w - q.y) / (6.0 * d + e)), d / (q.x + e), q.x);
    }

    vec3 HSVtoRGB(vec3 c)
    {
        vec4 K = vec4(1.0, 2.0 / 3.0, 1.0 / 3.0, 3.0);
        vec3 p = abs(fract(c.xxx + K.xyz) * 6.0 - K.www);
        return c.z * mix(K.xxx, clamp(p - K.xxx, 0.0, 1.0), c.y);
    }

    void main()
    {
        vec2 uv = v_UV;

        // 默认法线
        vec3 normalDir = normalize(v_NormalWS);

        #ifdef NORMALMAP
            vec2 uvN = uv * u_NormalTex_ST.xy + u_NormalTex_ST.zw;
            vec3 normalTS = texture2D(u_NormalTex, uvN).rgb;
            // 解码法线
            normalTS = normalize(normalTS * 2.0 - 1.0);

            #ifdef NORMALMAP_Y_INVERT
                normalTS.y *= -1.0;
            #endif

            // 应用法线强度
            if (u_NormalScale > 0.01) {
                float blendFactor = clamp(u_NormalScale, 0.0, 1.0);
                normalTS = normalize(mix(vec3(0.0, 0.0, 1.0), normalTS, blendFactor));
            }

            // 手动计算世界空间法线
            vec3 T = normalize(v_TangentWS);
            vec3 B = normalize(v_BinormalWS);
            vec3 N = normalize(v_NormalWS);

            normalDir = normalize(T * normalTS.x + B * normalTS.y + N * normalTS.z);
        #endif

        vec3 viewDir = safeNormalize(u_CameraPos - v_PositionWS);

        // 获取光照
        vec3 lightDir = vec3(0.0, 0.0, -1.0);
        vec3 lightColor = vec3(1.0, 1.0, 1.0);

        // 始终获取引擎灯光方向作为基础
        DirectionLight dirLight = getDirectionLight(0, v_PositionWS);
        lightDir = normalize(-dirLight.direction);
        lightColor = dirLight.color;

        // 应用灯光旋转
        float radX = radians(u_LightRotateX);
        float radY = radians(u_LightRotateY);
        float radZ = radians(u_LightRotateZ);

        // X轴旋转矩阵
        mat3 rotateX = mat3(
            1.0, 0.0, 0.0,
            0.0, cos(radX), -sin(radX),
            0.0, sin(radX), cos(radX)
        );

        // Y轴旋转矩阵
        mat3 rotateY = mat3(
            cos(radY), 0.0, sin(radY),
            0.0, 1.0, 0.0,
            -sin(radY), 0.0, cos(radY)
        );

        // Z轴旋转矩阵
        mat3 rotateZ = mat3(
            cos(radZ), -sin(radZ), 0.0,
            sin(radZ), cos(radZ), 0.0,
            0.0, 0.0, 1.0
        );

        // 组合旋转 (ZYX顺序)
        lightDir = rotateZ * rotateY * rotateX * lightDir;
        lightDir = normalize(lightDir);

        // 预防 lightColor 为全黑
        if (length(lightColor) < 0.01) {
            lightColor = vec3(1.0);
        }

        // 采样贴图
        vec2 uvM = uv * u_MainTex_ST.xy + u_MainTex_ST.zw;
        vec4 texCol = texture2D(u_MainTex, uvM);

        #ifdef Gamma_u_MainTex
            texCol = gammaToLinear(texCol);
        #endif // Gamma_u_MainTex



        texCol = pow(texCol, vec4(u_TexPower));

        vec2 uvS = uv * u_SpeTex_ST.xy + u_SpeTex_ST.zw;
        vec4 Specol = texture2D(u_SpeTex, uvS);




        //vec2 uvL = uv * u_LMap_ST.xy + u_LMap_ST.zw;
        vec4 SSA = texture2D(u_LMap, uv);

        #ifdef Gamma_u_LMap
            SSA = gammaToLinear(SSA);
        #endif
        SSA = pow(SSA, vec4(u_GammaPower));


        vec2 uvE = uv * u_EmissionTex_ST.xy + u_EmissionTex_ST.zw;
        vec4 EmissionCol = texture2D(u_EmissionTex, uvE);

        #ifdef Gamma_u_EmissionTex
            EmissionCol = gammaToLinear(EmissionCol);
        #endif // Gamma_u_EmissionTex
        EmissionCol = pow(EmissionCol, vec4(u_GammaPower));

        // 计算光照
        vec3 halfDir = safeNormalize(lightDir + viewDir);
        halfDir = normalize(halfDir + u_SpeOffet.xyz);

        float NdotL = dot(normalDir, lightDir);
        float NdotV = dot(normalDir, viewDir);
        float NdotH = dot(normalDir, halfDir);

        // 漫反射
        float lambert = clamp(NdotL * 0.5 + 0.5, 0.0, 1.0);

        vec3 diffuse;
        #ifdef USE_SECOND_LEVELS
            float ramp1 = calculateRamp(u_ShadowThreshold1, lambert, u_ShadowSmoothness);
            float ramp2 = calculateRamp(u_ShadowThreshold2, lambert, u_ShadowSmoothness);
            diffuse = mix(u_ShadowColor2.rgb, u_ShadowColor1.rgb, ramp2);
            diffuse = mix(diffuse, u_Color.rgb, ramp1);
        #else
            float ramp1 = calculateRamp(u_ShadowThreshold1, lambert, u_ShadowSmoothness);
            diffuse = mix(u_ShadowColor1.rgb, u_Color.rgb, ramp1);
        #endif
        diffuse *= texCol.rgb;

        // 高光
        float blinnPhong = pow(max(0.0, NdotH), u_SpecularPower);
        float specularRamp = calculateRamp(u_SpecularThreshold, blinnPhong, u_SpecularSmoothness);
        vec3 specularCol = u_SpecularColor.rgb * specularRamp * Specol.rgb * u_SpecularIntensity;

        // AO
        float ao = clamp(SSA.b, 0.05, 1.0);
        ao = mix(1.0, ao, u_AoPower);

        // 天空盒反射
        vec3 SkyColor = vec3(0.0);
        float skyMask = clamp(SSA.g, 0.0, 1.0);

        // 只在需要时计算天空盒反射
        if (u_IndirectStrength > 0.01 && skyMask > 0.01) {
            vec3 R = reflect(-viewDir, normalDir);

            // 应用天空盒旋转
            float skyRadX = radians(u_SkyRotateX);
            float skyRadY = radians(u_SkyRotateY);
            float skyRadZ = radians(u_SkyRotateZ);

            // X轴旋转矩阵
            mat3 skyRotateX = mat3(
                1.0, 0.0, 0.0,
                0.0, cos(skyRadX), -sin(skyRadX),
                0.0, sin(skyRadX), cos(skyRadX)
            );

            // Y轴旋转矩阵
            mat3 skyRotateY = mat3(
                cos(skyRadY), 0.0, sin(skyRadY),
                0.0, 1.0, 0.0,
                -sin(skyRadY), 0.0, cos(skyRadY)
            );

            // Z轴旋转矩阵
            mat3 skyRotateZ = mat3(
                cos(skyRadZ), -sin(skyRadZ), 0.0,
                sin(skyRadZ), cos(skyRadZ), 0.0,
                0.0, 0.0, 1.0
            );

            // 组合旋转应用到反射向量
            R = skyRotateZ * skyRotateY * skyRotateX * R;
            R = normalize(R);

            SkyColor = textureCube(u_CustomReflectTex, R).rgb * u_IndirectStrength * u_ReflectColor.rgb * skyMask;
        }

        vec3 result = (diffuse + specularCol) * ao * lightColor + SkyColor;

        // Rim 边缘光
        float rimMask = SSA.a;

         //float projection33 = u_Projection[3][3];  // 或者 u_ProjectionMatrix[2][3]

        // 判断相机类型

        //viewDir = vec3(0.0,0.0,1.0);
        if (u_Projection[3][3] > 0.5)
        {
            viewDir = vec3(0.0, 0.0, 1.0);
        }

        vec3 rimViewDir = normalize(viewDir + u_RimOffet.xyz);

        float NdotV_Rim = dot(normalDir, rimViewDir);

        #ifdef RIMSMOOTHNESS
            float rimFactor = clamp(1.0 - NdotV_Rim, 0.0001, 1.0);
            float rim = pow(rimFactor, u_RimWidth) * u_RimIntensity * rimMask;
            vec3 RimCol = rim * u_RimColor.rgb;
            result += RimCol;
        #else
            float rimFactor = clamp(1.0 - NdotV_Rim, 0.0001, 1.0);
            vec3 Rim = step(1.0 - u_RimWidth, rimFactor) * vec3(rimMask);
            vec3 RimCol = Rim * u_RimIntensity * u_RimColor.rgb;
            result = mix(result, RimCol, Rim.r);
        #endif

        // 自发光
        float EmissMask = SSA.r;
        vec3 EmColor = EmissionCol.rgb * u_EmissionPow * EmissMask;
        result += EmColor;

        // 色相调整
        vec3 hsv = RGBtoHSV(result.rgb);
        hsv.x += u_HueShift;
        hsv.x = fract(hsv.x);
        result.rgb = HSVtoRGB(hsv);

        // 对比度调整
        vec3 avgColor = vec3(0.5, 0.5, 0.5);
        result = mix(avgColor, result, u_Contrast);

        // 饱和度调整
        float luminance = dot(result.rgb, vec3(0.299, 0.587, 0.114));
        vec3 gray = vec3(luminance);
        result.rgb = mix(gray, result.rgb, u_Saturation);

        float alpha = texCol.a * u_Color.a;
        #ifdef ALPHATEST
            if (alpha < u_AlphaTestValue)
                discard;
        #endif

        gl_FragColor = vec4(result, alpha);
        gl_FragColor = outputTransform(gl_FragColor);
    }
#endGLSL
GLSL End
