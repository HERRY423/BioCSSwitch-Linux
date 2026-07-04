//! 模板注册表：单一来源（spec §5）。template_id 稳定持久于 Profile，据它派生
//! 运行 adapter（模型策略/鉴权/上限）与 UI 能力（是否必选模型 / URL 可编辑 / 内置模型）。
//! 前端 list_templates 取一次铺 UI，不在前端复制常量。

#[derive(Clone)]
pub struct Template {
    pub id: &'static str,
    pub name: &'static str,
    pub category: &'static str,   // official | cn_official | custom
    pub api_format: &'static str, // anthropic | openai_chat | openai_responses | gemini_native
    pub adapter: &'static str,    // 运行行为 → python 代理 --provider：deepseek | qwen | relay
    pub base_url: &'static str,   // 默认；空=用户填
    pub base_url_editable: bool,
    pub requires_model_override: bool,
    pub builtin_models: &'static [&'static str],
    pub website_url: &'static str,
    pub icon: &'static str,
    pub icon_color: &'static str,
}

pub fn all() -> &'static [Template] {
    TEMPLATES
}

pub fn by_id(id: &str) -> Option<&'static Template> {
    TEMPLATES.iter().find(|t| t.id == id)
}

/// 未命中 → "relay"（通用 anthropic 兼容透传，双鉴权）。
pub fn adapter_for(template_id: &str) -> &'static str {
    by_id(template_id).map(|t| t.adapter).unwrap_or("relay")
}

/// 旧固定槽 id → 新 template_id（迁移用）。未知/遗留裸 relay → custom。
pub fn template_id_for_legacy_slot(slot: &str) -> &'static str {
    match slot {
        "deepseek" => "deepseek",
        "qwen" => "qwen",
        "relay-glm" => "glm",
        "relay-xiaomi" => "xiaomi",
        "relay-siliconflow" => "siliconflow",
        "relay-openrouter" => "openrouter",
        _ => "custom",
    }
}

static TEMPLATES: &[Template] = &[
    Template {
        id: "deepseek",
        name: "DeepSeek",
        category: "cn_official",
        api_format: "anthropic",
        adapter: "deepseek",
        base_url: "https://api.deepseek.com/anthropic",
        base_url_editable: false,
        requires_model_override: false,
        builtin_models: &["claude-opus-4-8", "claude-haiku-4-5"],
        website_url: "https://platform.deepseek.com",
        icon: "deepseek",
        icon_color: "#1E88E5",
    },
    Template {
        id: "glm",
        name: "智谱 GLM",
        category: "cn_official",
        api_format: "anthropic",
        adapter: "relay",
        base_url: "https://open.bigmodel.cn/api/anthropic",
        base_url_editable: false,
        requires_model_override: false,
        builtin_models: &["glm-4.6", "glm-5", "glm-4.5-air"],
        website_url: "https://open.bigmodel.cn",
        icon: "glm",
        icon_color: "#2E6BE6",
    },
    Template {
        id: "xiaomi",
        name: "小米 MiMo",
        category: "cn_official",
        api_format: "anthropic",
        adapter: "relay",
        base_url: "https://api.xiaomimimo.com/anthropic",
        base_url_editable: false,
        requires_model_override: true,
        builtin_models: &["mimo-v2.5-pro"],
        website_url: "https://xiaomimimo.com",
        icon: "xiaomi",
        icon_color: "#FF6900",
    },
    Template {
        id: "siliconflow",
        name: "硅基流动",
        category: "cn_official",
        api_format: "anthropic",
        adapter: "relay",
        base_url: "https://api.siliconflow.cn",
        base_url_editable: false,
        requires_model_override: true,
        builtin_models: &["deepseek-ai/DeepSeek-V3", "zai-org/GLM-5.2"],
        website_url: "https://siliconflow.cn",
        icon: "siliconflow",
        icon_color: "#7C3AED",
    },
    Template {
        id: "openrouter",
        name: "OpenRouter",
        category: "custom",
        api_format: "anthropic",
        adapter: "relay",
        base_url: "https://openrouter.ai/api",
        base_url_editable: false,
        requires_model_override: false,
        builtin_models: &[
            "anthropic/claude-sonnet-5",
            "anthropic/claude-opus-4.8-fast",
        ],
        website_url: "https://openrouter.ai",
        icon: "openrouter",
        icon_color: "#6467F2",
    },
    Template {
        id: "qwen",
        name: "通义千问",
        category: "cn_official",
        api_format: "openai_chat",
        adapter: "qwen",
        base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1",
        base_url_editable: false,
        requires_model_override: false,
        builtin_models: &["qwen-max", "qwen-plus", "qwen-turbo"],
        website_url: "https://dashscope.aliyun.com",
        icon: "qwen",
        icon_color: "#615CED",
    },
    Template {
        id: "custom",
        name: "自定义",
        category: "custom",
        api_format: "anthropic",
        adapter: "relay",
        base_url: "",
        base_url_editable: true,
        requires_model_override: true,
        builtin_models: &[],
        website_url: "",
        icon: "custom",
        icon_color: "#6B7280",
    },
];

/// 遗留 provider=relay 单槽迁移（幂等）：在「旧 slot map + 旧 provider 指针」上把
/// 裸 `relay` 槽按 base_url 归位到 `relay-<preset>`。A4 迁移前先跑。返回是否改动。
pub fn migrate_legacy_relay(
    providers: &mut std::collections::BTreeMap<String, crate::config_legacy::ProviderCfgV1>,
    provider: &mut String,
) -> bool {
    let mut changed = false;
    let target = if let Some(slot) = providers.remove("relay") {
        let id = match_base_url(&slot.base_url).unwrap_or("relay-custom");
        providers.insert(id.to_string(), slot);
        changed = true;
        Some(id.to_string())
    } else {
        None
    };
    if provider == "relay" {
        *provider = target.unwrap_or_else(|| "deepseek".to_string());
        changed = true;
    }
    changed
}

/// 旧「relay-<preset>」槽 id ↔ base_url（迁移遗留裸 relay 用）。空 base_url → None。
fn match_base_url(url: &str) -> Option<&'static str> {
    let norm = url.trim().trim_end_matches('/');
    if norm.is_empty() {
        return None;
    }
    [
        ("relay-glm", "https://open.bigmodel.cn/api/anthropic"),
        ("relay-xiaomi", "https://api.xiaomimimo.com/anthropic"),
        ("relay-siliconflow", "https://api.siliconflow.cn"),
        ("relay-openrouter", "https://openrouter.ai/api"),
    ]
    .iter()
    .find(|(_, b)| *b == norm)
    .map(|(id, _)| *id)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config_legacy::ProviderCfgV1;
    use std::collections::BTreeMap;

    #[test]
    fn table_has_seven_templates() {
        let ids: Vec<&str> = all().iter().map(|t| t.id).collect();
        assert_eq!(
            ids,
            vec![
                "deepseek",
                "glm",
                "xiaomi",
                "siliconflow",
                "openrouter",
                "qwen",
                "custom"
            ]
        );
    }

    #[test]
    fn adapter_mapping_is_correct() {
        assert_eq!(adapter_for("deepseek"), "deepseek");
        assert_eq!(adapter_for("qwen"), "qwen");
        assert_eq!(adapter_for("glm"), "relay");
        assert_eq!(adapter_for("openrouter"), "relay");
        assert_eq!(adapter_for("custom"), "relay");
        assert_eq!(adapter_for("unknown-xyz"), "relay"); // 兜底
    }

    #[test]
    fn api_format_reflects_real_protocol() {
        assert_eq!(by_id("deepseek").unwrap().api_format, "anthropic");
        assert_eq!(by_id("glm").unwrap().api_format, "anthropic");
        assert_eq!(by_id("qwen").unwrap().api_format, "openai_chat");
    }

    #[test]
    fn requires_model_override_matches_capability() {
        assert!(by_id("xiaomi").unwrap().requires_model_override);
        assert!(by_id("siliconflow").unwrap().requires_model_override);
        assert!(!by_id("glm").unwrap().requires_model_override);
        assert!(!by_id("openrouter").unwrap().requires_model_override);
        assert!(by_id("custom").unwrap().requires_model_override);
    }

    #[test]
    fn legacy_slot_maps_to_template_id() {
        assert_eq!(template_id_for_legacy_slot("deepseek"), "deepseek");
        assert_eq!(template_id_for_legacy_slot("qwen"), "qwen");
        assert_eq!(template_id_for_legacy_slot("relay-glm"), "glm");
        assert_eq!(template_id_for_legacy_slot("relay-xiaomi"), "xiaomi");
        assert_eq!(
            template_id_for_legacy_slot("relay-siliconflow"),
            "siliconflow"
        );
        assert_eq!(
            template_id_for_legacy_slot("relay-openrouter"),
            "openrouter"
        );
        assert_eq!(template_id_for_legacy_slot("relay-custom"), "custom");
        assert_eq!(template_id_for_legacy_slot("relay"), "custom"); // 遗留裸 relay 兜底
        assert_eq!(template_id_for_legacy_slot("weird"), "custom");
    }

    #[test]
    fn custom_has_empty_editable_base_url() {
        let c = by_id("custom").unwrap();
        assert_eq!(c.base_url, "");
        assert!(c.base_url_editable);
    }

    fn slot(base_url: &str) -> ProviderCfgV1 {
        ProviderCfgV1 {
            key: "legacy_key".into(),
            base_url: base_url.into(),
            model: String::new(),
        }
    }

    #[test]
    fn migrate_known_base_url_moves_to_matched_preset() {
        let mut providers = BTreeMap::new();
        providers.insert(
            "relay".to_string(),
            slot("https://open.bigmodel.cn/api/anthropic"),
        );
        let mut provider = "relay".to_string();
        assert!(migrate_legacy_relay(&mut providers, &mut provider));
        assert_eq!(provider, "relay-glm");
        assert!(!providers.contains_key("relay"), "旧 relay 槽应删除");
        assert_eq!(providers.get("relay-glm").unwrap().key, "legacy_key");
    }

    #[test]
    fn migrate_unknown_base_url_falls_to_custom() {
        let mut providers = BTreeMap::new();
        providers.insert("relay".to_string(), slot("https://unknown.example/relay"));
        let mut provider = "relay".to_string();
        assert!(migrate_legacy_relay(&mut providers, &mut provider));
        assert_eq!(provider, "relay-custom");
        assert_eq!(providers.get("relay-custom").unwrap().key, "legacy_key");
    }

    #[test]
    fn migrate_provider_relay_without_slot_falls_to_deepseek() {
        let mut providers: BTreeMap<String, ProviderCfgV1> = BTreeMap::new();
        let mut provider = "relay".to_string();
        assert!(migrate_legacy_relay(&mut providers, &mut provider));
        assert_eq!(provider, "deepseek");
    }

    #[test]
    fn migrate_is_noop_on_new_config() {
        let mut providers: BTreeMap<String, ProviderCfgV1> = BTreeMap::new();
        providers.insert(
            "relay-glm".to_string(),
            slot("https://open.bigmodel.cn/api/anthropic"),
        );
        let mut provider = "relay-glm".to_string();
        assert!(!migrate_legacy_relay(&mut providers, &mut provider));
        assert_eq!(provider, "relay-glm");
    }
}
