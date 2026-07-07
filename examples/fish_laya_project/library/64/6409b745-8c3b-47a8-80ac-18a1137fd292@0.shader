Shader3D Start
{
    type:Shader3D,
    name:Particle2D,
    enableInstancing:false,
    supportReflectionProbe:true,
    shaderType:Default,
    uniformMap:{
        u_Texture: { type: Texture2D, default: "white" },
    },
    attributeMap: {
        'a_PositionAndUV': ["Vector4", 0],

        "a_DirectionAndPosition": ["Vector4", 8],
        "a_SizeAndTimes": ["Vector4", 9],
        "a_SpeedSpaceAndRot": ["Vector4", 10],
        "a_StartColor": ["Vector4", 11],
        "a_SpriteRotAndSacle": ["Vector4", 12],
        "a_SpriteTransAndGravity": ["Vector4", 13],
        "a_Random": ["Vector4", 14],
        "a_Random1": ["Vector4", 15],
        "a_SheetFrameData": ["Vector4", 7],
    },


    defines: {
    }
    shaderPass:[
        {
            pipeline:Forward,
            VS:textureVS,
            FS:texturePS,
        }
    ]
}
Shader3D End

GLSL Start
#defineGLSL textureVS

    #define SHADER_NAME Particle2D
    
    #include "Color.glsl";

    #include "./lib/2d/Particle2DVertex.glsl";

    void main() {
        Particle particle = getParticle();

        if (particle.age > particle.lifetime || particle.age < 0.0) 
        {
            gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
            return;
        }

        vec4 position = updateParticlePosition(particle);

        shareParticleParams(particle);

        gl_Position = position;
    }

#endGLSL

#defineGLSL texturePS

#define SHADER_NAME Particle2D

    #include "Color.glsl";

    #include "./lib/2d/Particle2DFrag.glsl";

    void main()
    {
        clip();

        vec4 particleColor = getParticleColor();
        vec2 particleUV = getParticleUV();

        vec3 color = particleColor.rgb;
        float alpha = particleColor.a;

        vec4 textureSampler = texture2D(u_Texture, particleUV);
        #ifdef Gamma_u_Texture
        textureSampler = gammaToLinear(textureSampler);
        #endif // Gamma_u_Texture

        color *= textureSampler.rgb;
        alpha *= textureSampler.a;

        gl_FragColor = vec4(color, alpha);
    }
    
#endGLSL
GLSL End
