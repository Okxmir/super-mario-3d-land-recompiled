// Convert rotated PICA rows to an upright 3DS LCD image.
[[vk::combinedImageSampler]] Texture2D<float4> Source : register(t0, space2);
[[vk::combinedImageSampler]] SamplerState Filter : register(s0, space2);

cbuffer Blit : register(b0, space3) {
    float4 Size;
    int4 Mode;
};

float4 main(float4 position : SV_Position) : SV_Target0 {
    int x = int(Size.y) - 1 - int(position.y);
    int y = (Mode.x & 1) != 0 ? int(Size.x) - 1 - int(position.x) : int(position.x);
    float2 block = float2(1 << Mode.y, 1 << Mode.z);
    float2 texel = (float2(x, y) + float2(0, Mode.w)) * block + block * 0.5;
    float3 sampled = Source.SampleLevel(Filter, texel / Size.zw, 0).rgb;
    if ((Mode.x & 2) == 0) return float4(sampled, 1.0);
    uint3 rgb = uint3(saturate(sampled) * 255.0 + 0.5);
    uint r = rgb.r >> 3, g = rgb.g >> 2, b = rgb.b >> 3;
    return float4(float3((r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)) / 255.0, 1.0);
}
