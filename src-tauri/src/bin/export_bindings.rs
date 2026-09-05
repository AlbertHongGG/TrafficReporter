fn main() {
    app_lib::create_builder()
        .export(
            specta_typescript::Typescript::default(),
            "../src/types/bindings.ts",
        )
        .expect("Failed to export specta types");
}
