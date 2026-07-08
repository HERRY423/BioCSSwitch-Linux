use serde_json::{json, Value};

pub(crate) const FORCED_MODEL_SHELL_ID: &str = "claude-opus-4-8";
const MODEL_CREATED_AT: &str = "2026-01-01T00:00:00Z";

#[derive(Clone, Debug, PartialEq)]
pub(crate) struct ModelSpec {
    pub(crate) id: String,
    pub(crate) display_name: String,
    pub(crate) supports_tools: Option<bool>,
}

impl ModelSpec {
    pub(crate) fn new(id: impl Into<String>, display_name: impl Into<String>) -> Self {
        Self {
            id: id.into(),
            display_name: display_name.into(),
            supports_tools: None,
        }
    }

    pub(crate) fn with_tool_support(mut self, supports_tools: Option<bool>) -> Self {
        self.supports_tools = supports_tools;
        self
    }
}

pub(crate) fn models_response(models: &[ModelSpec]) -> Value {
    let data: Vec<Value> = models
        .iter()
        .map(|m| {
            json!({
                "type": "model",
                "id": m.id.as_str(),
                "display_name": m.display_name.as_str(),
                "supports_tools": m.supports_tools,
                "created_at": MODEL_CREATED_AT,
            })
        })
        .collect();
    json!({
        "data": data,
        "has_more": false,
        "first_id": models.first().map(|m| m.id.as_str()),
        "last_id": models.last().map(|m| m.id.as_str()),
    })
}

pub(crate) fn forced_model_response(display_name: &str) -> Value {
    models_response(&[ModelSpec::new(FORCED_MODEL_SHELL_ID, display_name)])
}

pub(crate) fn static_models_response(models: &[(&str, &str)]) -> Value {
    let specs: Vec<ModelSpec> = models
        .iter()
        .map(|(id, display_name)| ModelSpec::new(*id, *display_name))
        .collect();
    models_response(&specs)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn forced_model_response_uses_science_shell_id() {
        let body = forced_model_response("glm-5.2");
        assert_eq!(body["data"][0]["id"], FORCED_MODEL_SHELL_ID);
        assert_eq!(body["data"][0]["display_name"], "glm-5.2");
        assert_eq!(body["first_id"], FORCED_MODEL_SHELL_ID);
        assert_eq!(body["last_id"], FORCED_MODEL_SHELL_ID);
        assert_eq!(body["has_more"], false);
    }

    #[test]
    fn models_response_keeps_tool_capability_tri_state() {
        let body = models_response(&[
            ModelSpec::new("glm-4.6", "GLM 4.6").with_tool_support(Some(true)),
            ModelSpec::new("glm-lite", "GLM Lite").with_tool_support(Some(false)),
            ModelSpec::new("glm-x", "GLM X"),
        ]);
        assert_eq!(body["data"][0]["supports_tools"], true);
        assert_eq!(body["data"][1]["supports_tools"], false);
        assert!(body["data"][2]["supports_tools"].is_null());
        assert_eq!(body["first_id"], "glm-4.6");
        assert_eq!(body["last_id"], "glm-x");
    }

    #[test]
    fn static_models_response_matches_python_builtin_shape() {
        let body = static_models_response(&[
            ("claude-opus-4-8", "DeepSeek V4 Pro"),
            ("claude-haiku-4-5", "DeepSeek V4 Flash"),
        ]);
        assert_eq!(body["data"][0]["type"], "model");
        assert_eq!(body["data"][0]["created_at"], MODEL_CREATED_AT);
        assert_eq!(body["data"][1]["display_name"], "DeepSeek V4 Flash");
        assert_eq!(body["has_more"], false);
    }
}
