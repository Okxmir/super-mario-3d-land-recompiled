"""Classify complete triangle lists without copying their already shaded vertices."""
from coherent_pica_fast import once


def direct_widescreen_lists(source):
    source = once(source, 'bool deferring = false;', 'bool deferring = false;\nbool direct_classification = false;')
    source = once(source, '''bool fills_screen(const std::vector<Vertex> &tris) {
    if (tris.empty()) return false;''', '''template<class VertexAt>
bool fills_screen(size_t count, VertexAt vertex_at) {
    if (!count) return false;''')
    source = once(source, '    for (size_t i = 0; i + 2 < tris.size(); i += 3) {\n        float x[3], y[3];',
        '    for (size_t i = 0; i + 2 < count; i += 3) {\n        float x[3], y[3];')
    source = once(source, 'const float *a = tris[i + size_t(k)].a;', 'const float *a = vertex_at(i + size_t(k)).a;')
    source = once(source, '''int side_of(const std::vector<Vertex> &tris) {
    float xlo = 1e9f, xhi = -1e9f, ylo = 1e9f, yhi = -1e9f;
    for (const Vertex &v : tris) {''', '''template<class VertexAt>
int side_of(size_t count, VertexAt vertex_at) {
    float xlo = 1e9f, xhi = -1e9f, ylo = 1e9f, yhi = -1e9f;
    for (size_t i = 0; i < count; ++i) {
        const Vertex &v = vertex_at(i);''')
    source = once(source, 'yhi - ylo > 1.0f && tris.size() >= 24)', 'yhi - ylo > 1.0f && count >= 24)')
    source = once(source, '''        for (size_t i = 0; i + 2 < tris.size(); i += 3) {
            const float *a = tris[i].a, *b = tris[i + 1].a, *c = tris[i + 2].a;''',
        '''        for (size_t i = 0; i + 2 < count; i += 3) {
            const float *a = vertex_at(i).a, *b = vertex_at(i + 1).a, *c = vertex_at(i + 2).a;''')
    source = once(source, '''    draw_fills_screen = false;
}

void finish_deferring() {
    draw_geom.valid = false;''', '''    draw_fills_screen = false;
    direct_classification = false;
}

void finish_deferring() {
    if (direct_classification) {
        // The GPU's end_draw still consumes the classified geometry.
        draw_fills_screen = false;
        draw_anchor = 0;
        direct_classification = false;
        return;
    }
    draw_geom.valid = false;''')
    source = once(source, '''    draw_fills_screen = stats.fills = fills_screen(deferred);
    draw_anchor = draw_fills_screen ? 0 : side_of(deferred);''', '''    const auto vertex_at = [](size_t i) -> const Vertex & { return deferred[i]; };
    draw_fills_screen = stats.fills = fills_screen(deferred.size(), vertex_at);
    draw_anchor = draw_fills_screen ? 0 : side_of(deferred.size(), vertex_at);''')
    return once(source, '''        if (topology != 1 && topology != 2 && list_count == 0) {
            // Complete lists can be emitted directly from the shaded vertices.''', '''        if (topology != 1 && topology != 2 && list_count == 0) {
            static const bool disabled = std::getenv("SM3DL_LAB_DEFER_LISTS") != nullptr;
            const uint32_t complete = count - count % 3;
            if (!disabled && deferring && complete && deferred.empty() && gpu::active()) {
                // Both classifiers see the same emitted vertices in the same
                // order. Keep the 2D anchors, widescreen and culling unchanged.
                draw_geom.valid = false;
                draw_fills_screen = stats.fills = fills_screen(complete, vertex_at);
                draw_anchor = draw_fills_screen ? 0 : side_of(complete, vertex_at);
                deferring = false;
                direct_classification = true;
            }
            // Complete lists can be emitted directly from the shaded vertices.''')
