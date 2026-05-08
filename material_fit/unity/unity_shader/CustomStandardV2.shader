Shader "CustomStandardV2"
{
    Properties
    {
        _Color("Color", Color) = (1,1,1,1)
        _MainTex("Albedo", 2D) = "white" {}
        _ColorScale("Color Scale", Range(1.0,10.0)) = 1.0
        _Cutoff("Alpha Cutoff", Range(0.0, 1.0)) = 0.5

        _Glossiness("Smoothness", Range(0.0, 1.0)) = 0.5
        _GlossMapScale("Smoothness Scale", Range(-1.0, 1.0)) = -0.8
        _SmoothnessRemapMin("Smoothness RemapMin", Float) = 0.0
        _SmoothnessRemapMax("Smoothness RemapMax", Float) = 1.0

        [Gamma] _Metallic("Metallic", Range(0.0, 1.0)) = 0.0
        _MetallicGlossMap("Metallic", 2D) = "white" {}
        _MetallicRemapMin("Metallic RemapMin", Float) = 0.0
        _MetallicRemapMax("Metallic RemapMax", Float) = 1.0

        [ToggleOff] _SpecularHighlights("Specular Highlights", Float) = 1.0
        [ToggleOff] _GlossyReflections("Glossy Reflections", Float) = 1.0
        [ToggleOff] _NotFixSubstance("Not Fix Substance's roughness", Float) = 1.0

		[Toggle] _HeightFog("Height Fog", Float) = 0.0
		_HeightFogColor("Height Fog Color", Color) = (0,0,1.0)
		_HeightFogDensity("Height Fog Density", Float) = 1.0
		_HeightFogStart("Height Fog Start", Float) = -10
		_HeightFogEnd("Height Fog End", Float) = 10.0

		[Toggle] _RimLight("Rim Light", Float) = 0.0
		[HDR]_RimColor("Rim Color", Color) = (0.5,0.5,0.5,1.0)
		_RimPower("Rim Power", Range(0.01, 10)) = 0.01
		_RimSpread("Rim Spread", Range(-15, 4.99)) = 0.01
		_RimOffset("Rim Offset", Vector) = (0,0,0,0)

		[Toggle] _Translucent("Translucent", Float) = 0.0
		_Translucency("Translucency", Range(0 , 50)) = 20
		_TransScattering("Scaterring Falloff", Range(1 , 50)) = 10
		_TransDirect("Trans Direct", Range(0 , 1)) = 0.1
		_TransAmbient("Trans Ambient", Range(0 , 1)) = 0
		_TransColor("Trans Color", Color) = (1.0,0,0,0)
		_TransMap("Trans Map", 2D) = "black" {}
		[Enum(Trans Map,0,Metallic B,1)] _TransMapChannel ("Translucent map channel", Float) = 0
		
		[Toggle] _AdjustHSV("Adjust HSV", Float) = 0.0
		_AdjustHue("Hue", Range(0,360)) = 0.0
		_AdjustSaturation("Saturation", Range(0,5)) = 1.0
		_AdjustValue("Value", Range(0,5)) = 1.0

        _BumpScale("Scale", Float) = 1.0
        _BumpMap("Normal Map", 2D) = "bump" {}

        _OcclusionStrength("Strength", Range(0.0, 1.0)) = 1.0

        [Toggle] _Emission("Emission",Int) = 0
        [HDR]_EmissionColor("Color", Color) = (0,0,0)
        _EmissionTexture("Emission", 2D) = "white" {}
        [Enum(Metallic B,0,Emission Texture,1)] _EmissionMapChannel ("Emission map channel", Float) = 0

        // Blending state
        [HideInInspector] _Mode ("__mode", Float) = 0.0
        [HideInInspector] _SrcBlend ("__src", Float) = 1.0
        [HideInInspector] _DstBlend ("__dst", Float) = 0.0
        [HideInInspector] _ZWrite ("__zw", Float) = 1.0
        
        // Double sided
        [HideInInspector] _CullMode("__cullMode", Float) = 2.0

        //Shadow
        [Toggle] _Shadow("Shadow",Float) = 0.0        
        [Toggle] _ShadowOffsetToggle("ShadowOffsetToggle",Float) = 1.0        
        _ShadowOffset("_Offset",Vector) = (-0.5,-1,2 ,0)
        _ShadowColor("_Color",Color) = (0,0,0,0.8)

        //Projection
        [Toggle] _Perspective("Perspective",Float) = 0.0

        //OverlayColor
        [Toggle] _Overlay("Hit Color",Int) = 0
        [KeywordEnum(Rim,Albedo)] _HitColorChannel("HitColorType",Float) = 0
        //calculate hit color data
        _OverlayColor("Color",Color) = (1,1,1,1)
        _FinalColor("Color",Color) = (1,1,1,1)
        _OverlayMultiple("Multiple",Float) = 1
        _OverlayRimPower("Rim Power", Range(0.01, 10)) = 0.01
        _OverlayRimSpread("Rim Spread", Range(0, 4.99)) = 0.01
        _OverlayRimOffset("Rim Offset", Vector) = (0,0,0,0)
        //cache hit color
		[HDR]_HitColor("Color",Color) = (1,1,1,1)
        _HitMultiple("Multiple",Float) = 1
        _HitRimPower("Rim Power", Range(0.01, 10)) = 0.01
        _HitRimSpread("Rim Spread", Range(-15, 4.99)) = 0.01
        _HitRimOffset("Rim Offset", Vector) = (0,0,0,0)

        //Streamer
        [Toggle] _Streamer("Streamer",Int) = 0
        _StreamerTex("Texture",2D) = "white"{}
        _StreamerMask("Mask",2D) = "white"{}
        _StreamerNoise("Noise",2D) = "white"{}
        _StreamerNoiseSpeed("NoiseSpeed",Float) = 1.0
        _StreamerColor("Color",Color) = (1,1,1,1)
        _StreamerAlpha("Alpha",Float) = 1
        _StreamerScrollX("speed X", Float) = 1.0
        _StreamerScrollY("speed Y", Float) = 0.0
        [KeywordEnum(UVPos,ScreenPos,ModelPos)] _StreamerChannel("StreamerType",Float) = 0

		[Toggle] _Contrast("AdjustContrast", Float) = 0.0
		_ContrastScale("ContrastSacle",Range(0,2)) = 1
		//Reflect
		[Toggle]_Reflect("Reflect", Float) = 0
		_ReflectCubMap("Reflect CubeMap", Cube) = "_Skybox"{}
		_ReflectMask("Reflect Mask", 2D) = "white"{}
		[HDR]_ReflectColor("Reflect Color" , Color) = (0,0,0,1)
		_ReflectStrength("Reflect Strength" ,Range(0,2)) = 0
		_ReflectMode("Reflect Mode", Range(0, 1)) = 1

		_ViewDirTex1("ViewDirTex1", 2D) = "white" {}
		[HDR]_SpecColor02("Spec Color", Color) = (0, 0, 0, 1)
		_TimeScale("Time Sca1e", Range(0, 10)) = 0
		_SpecScale("SpecScale",Range(0.01,3)) = 1
		_SpecStrength("Spec Strength", Range(0, 10)) = 0

        _Alpha("Alpha",Range(0,1)) =1

    }

    CGINCLUDE
        #define UNITY_SETUP_BRDF_INPUT MetallicSetup
    ENDCG

    SubShader
    {
        Tags { "RenderType"="Opaque" "PerformanceChecks"="False" }
        LOD 300
        // ------------------------------------------------------------------
        //  Base forward pass (directional light, emission, lightmaps, ...)
        Pass
        {
            Name "FORWARD"
            Tags { "LightMode" = "ForwardBase" }

            Blend [_SrcBlend] [_DstBlend]
            ZWrite [_ZWrite] 
            Cull [_CullMode]
            
             Stencil {
                Ref 3
                Pass IncrSat
             }            
           
            CGPROGRAM
            #pragma target 3.0

            // -------------------------------------
            #pragma shader_feature _NORMALMAP
            // #pragma shader_feature _EMISSION
            #pragma shader_feature _EMISSION_OFF _EMISSION_MAP_TEXTURE _MAERMAP_B
            #pragma shader_feature _METALLICGLOSSMAP
            #pragma shader_feature _ _SPECULARHIGHLIGHTS_OFF
            #pragma shader_feature _ _GLOSSYREFLECTIONS_OFF
            #pragma shader_feature _ _NOTFIXSUBSTANCE_OFF
            //#pragma shader_feature _PARALLAXMAP
            //#pragma shader_feature _PLANARREFLECTIONS_ON
            #pragma shader_feature _HEIGHTFOG_ON
            #pragma shader_feature _RIMLIGHT_ON
			#pragma shader_feature _TRANSLUCENT_ON
			#pragma shader_feature _ _TRANS_TEXTURE_METALLIC_CHANNEL_B
			#pragma shader_feature _ADJUSTHSV_ON
			#pragma shader_feature _PERSPECTIVE_ON
            #pragma shader_feature _OVERLAY_ON
            //#pragma shader_feature _STREAMER_ON
            #pragma shader_feature _STREAMER_OFF _STREAMERCHANNEL_UVPOS _STREAMERCHANNEL_SCREENPOS _STREAMERCHANNEL_MODELPOS
            #pragma shader_feature _HITCOLORCHANNEL_RIM _HITCOLORCHANNEL_ALBEDO
            #pragma shader_feature _CONTRAST_ON
			#pragma shader_feature _REFLECT_ON
			//#pragma shader_feature _OUTLINE_ON

            #pragma multi_compile _ALPHATEST_ON _ALPHABLEND_ON _ALPHAPREMULTIPLY_ON
            #pragma multi_compile DIRECTIONAL
            #pragma multi_compile SHADOWS_OFF SHADOWS_DEPTH
            #pragma multi_compile LIGHTPROBE_SH
            #pragma multi_compile_instancing
            #pragma vertex vertForwardBase
            #pragma fragment fragForwardBase
            #include "CustomStandardCore.cginc"

            ENDCG
        }
        
        Pass
        {
            Name "FORWARD_DELTA"
            Tags { "LightMode" = "ForwardAdd" }
            Blend [_SrcBlend] One
            Fog { Color (0,0,0,0) } // in additive pass fog should be black
            ZWrite Off
            ZTest LEqual

            CGPROGRAM
            #pragma target 3.0

            // -------------------------------------
            #pragma shader_feature _NORMALMAP
            #pragma shader_feature _METALLICGLOSSMAP
            #pragma shader_feature _ _SPECULARHIGHLIGHTS_OFF
            #pragma shader_feature _ _NOTFIXSUBSTANCE_OFF
            //#pragma shader_feature _PARALLAXMAP

            #pragma multi_compile_fwdadd_fullshadows
            //#pragma multi_compile_fog
            #pragma multi_compile _ALPHATEST_ON _ALPHABLEND_ON _ALPHAPREMULTIPLY_ON
            #pragma vertex vertForwardAdd
            #pragma fragment fragForwardAdd
            #include "CustomStandardCore.cginc"

            ENDCG
        }

        Pass 
		{
			Name "SHADOW"
            Tags  {"LightMode" = "ALWAYS" "Queue"="Transparent" "RenderType" = "Transparent"}

            Stencil
		   {
                Ref 1
                Comp greater
                Pass replace
            }

            ZWrite Off
            Blend SrcAlpha OneMinusSrcAlpha
            
            CGPROGRAM          
            #pragma shader_feature _PERSPECTIVE_ON
            #pragma shader_feature _SHADOW_ON
            #pragma shader_feature _SHADOWOFFSETTOGGLE_ON
            #pragma vertex vertShadow
            #pragma fragment fragShadow

            #include "CustomStandardCore.cginc"
           
            ENDCG
        }   

		
    }

    SubShader
    {
        Tags { "RenderType" = "Opaque" "PerformanceChecks" = "False" }
        LOD 150
        Pass
        {
            Name "FORWARD"
            Tags { "LightMode" = "ForwardBase" }

            Blend[_SrcBlend][_DstBlend]
            ZWrite[_ZWrite]
            Cull[_CullMode]

             Stencil {
                Ref 0
                Pass IncrSat
            }

            CGPROGRAM
            #pragma target 3.0

        // -------------------------------------
        #pragma shader_feature _NORMALMAP
        // #pragma shader_feature _EMISSION
        #pragma shader_feature _EMISSION_OFF _EMISSION_MAP_TEXTURE _MAERMAP_B
        #pragma shader_feature _METALLICGLOSSMAP
        #pragma shader_feature _ _SPECULARHIGHLIGHTS_OFF
        #pragma shader_feature _ _GLOSSYREFLECTIONS_OFF
        #pragma shader_feature _ _NOTFIXSUBSTANCE_OFF
        //#pragma shader_feature _PARALLAXMAP
        //#pragma shader_feature _PLANARREFLECTIONS_ON
        #pragma shader_feature _HEIGHTFOG_ON
        #pragma shader_feature _RIMLIGHT_ON
        #pragma shader_feature _TRANSLUCENT_ON
        #pragma shader_feature _ _TRANS_TEXTURE_METALLIC_CHANNEL_B
        #pragma shader_feature _ADJUSTHSV_ON
        #pragma shader_feature _PERSPECTIVE_ON
        #pragma shader_feature _OVERLAY_ON

		#pragma shader_feature _CONTRAST_ON
		#pragma shader_feature _REFLECT_ON

        //#pragma shader_feature _STREAMER_ON
        #pragma shader_feature _STREAMER_OFF _STREAMERCHANNEL_UVPOS _STREAMERCHANNEL_SCREENPOS _STREAMERCHANNEL_MODELPOS
        #pragma shader_feature _HITCOLORCHANNEL_RIM _HITCOLORCHANNEL_ALBEDO

        #pragma multi_compile DIRECTIONAL
        #pragma multi_compile SHADOWS_OFF SHADOWS_DEPTH
        #pragma multi_compile LIGHTPROBE_SH
        //#pragma multi_compile_fwdbase
        //#pragma multi_compile_fog
        #pragma multi_compile_instancing          
        #pragma multi_compile _ALPHATEST_ON _ALPHABLEND_ON _ALPHAPREMULTIPLY_ON

        #pragma vertex vertForwardBase
        #pragma fragment fragForwardBase
        #include "CustomStandardCore.cginc"

        ENDCG
    }

        Pass
        {
            Name "FORWARD_DELTA"
            Tags { "LightMode" = "ForwardAdd" }
            Blend[_SrcBlend] One
            Fog { Color(0,0,0,0) } // in additive pass fog should be black
            ZWrite Off
            ZTest LEqual

            CGPROGRAM
            #pragma target 3.0

        // -------------------------------------
        #pragma shader_feature _NORMALMAP
        #pragma shader_feature _METALLICGLOSSMAP
        #pragma shader_feature _ _SPECULARHIGHLIGHTS_OFF
        #pragma shader_feature _ _NOTFIXSUBSTANCE_OFF
        //#pragma shader_feature _PARALLAXMAP

        #pragma multi_compile_fwdadd_fullshadows
        //#pragma multi_compile_fog           
        #pragma multi_compile _ALPHATEST_ON _ALPHABLEND_ON _ALPHAPREMULTIPLY_ON
        #pragma vertex vertForwardAdd
        #pragma fragment fragForwardAdd
        #include "CustomStandardCore.cginc"

        ENDCG
    }
    }

    FallBack "VertexLit"
    CustomEditor "CustomStandardGUIV2"
}