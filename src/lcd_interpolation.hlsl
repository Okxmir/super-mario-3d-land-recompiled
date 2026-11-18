// Estimate a single screen translation. Local warps deform textures at depth boundaries.
[[vk::combinedImageSampler]] Texture2D<float4> Previous : register(t0, space2);
[[vk::combinedImageSampler]] SamplerState PreviousSampler : register(s0, space2);
[[vk::combinedImageSampler]] Texture2D<float4> Current : register(t1, space2);
[[vk::combinedImageSampler]] SamplerState CurrentSampler : register(s1, space2);
[[vk::combinedImageSampler]] Texture2D<float4> Scores : register(t0, space0);
[[vk::combinedImageSampler]] SamplerState ScoreSampler : register(s0, space0);

static const float2 NativeSize = float2(400, 240);
static const int Radius = 4;

float difference(float3 a, float3 b) {
    return dot(abs(a - b), float3(0.25, 0.5, 0.25));
}

// One candidate per fragment. Sample the same positions across the whole screen
// to reject parallax, stationary overlays and cuts before moving any pixels.
float4 estimate(float4 position : SV_Position) : SV_Target0 {
    uint width, height;
    Current.GetDimensions(width, height);
    float2 nativeSize = float2(width, height) * (NativeSize.y / float(height));
    float2 delta = (int2(position.xy) - Radius) / nativeSize;
    float sum = 0.0;
    int improved = 0, conflicts = 0, mismatches = 0;
    const int Columns = 10, Rows = 8;
    [loop] for (int y = 0; y < Rows; ++y) {
        [loop] for (int x = 0; x < Columns; ++x) {
            float2 uv = (float2(x, y) + 0.5) / float2(Columns, Rows);
            float original = difference(Previous.SampleLevel(PreviousSampler, uv, 0).rgb,
                                        Current.SampleLevel(CurrentSampler, uv, 0).rgb);
            float shifted = difference(Previous.SampleLevel(PreviousSampler, uv - delta, 0).rgb,
                                       Current.SampleLevel(CurrentSampler, uv + delta, 0).rgb);
            sum += shifted;
            improved += original > shifted + 0.022 ? 1 : 0;
            conflicts += original < 0.015 && shifted > 0.045 ? 1 : 0;
            mismatches += shifted > 0.095 ? 1 : 0;
        }
    }
    return float4(sum, improved, conflicts, mismatches) / (Columns * Rows);
}

struct ScreenVertex {
    float4 position : SV_Position;
    nointerpolation int2 motion : TEXCOORD0;
};

// The fullscreen triangle shares one result across all pixels. Choosing it in
// the vertex shader avoids a third render pass and another texture transition.
ScreenVertex screen_motion(uint id : SV_VertexID) {
    float original = Scores.Load(int3(Radius, Radius, 0)).r;
    float best = original - 0.012;
    int2 motion = 0;
    [loop] for (int y = -Radius; y <= Radius; ++y) {
        [loop] for (int x = -Radius; x <= Radius; ++x) {
            float4 result = Scores.Load(int3(x + Radius, y + Radius, 0));
            if (result.r > 0.033 || result.g < 0.22 || result.b > 0.025 || result.a > 0.10) continue;
            float cost = result.r + 0.0015 * (abs(x) + abs(y));
            if (cost < best) {
                best = cost;
                motion = int2(x, y);
            }
        }
    }
    const float2 positions[3] = {float2(-1.0, -1.0), float2(3.0, -1.0), float2(-1.0, 3.0)};
    ScreenVertex result;
    result.position = float4(positions[id], 0.0, 1.0);
    result.motion = motion;
    return result;
}

float4 interpolate(ScreenVertex vertex) : SV_Target0 {
    uint width, height;
    Current.GetDimensions(width, height);
    int2 pos = int2(vertex.position.xy);
    int2 shift = vertex.motion * int(height / (uint)NativeSize.y);
    int2 previousPos = pos - shift;
    if (all(previousPos >= 0) && all(previousPos < int2(width, height)))
        return Previous.Load(int3(previousPos, 0));
    // The current image supplies the strip newly revealed by the camera pan.
    return Current.Load(int3(clamp(pos + shift, int2(0, 0), int2(width, height) - 1), 0));
}
