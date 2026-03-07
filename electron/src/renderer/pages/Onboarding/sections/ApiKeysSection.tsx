import HelpRail from "../components/HelpRail";
import SectionHeader from "../components/SectionHeader";
import TokenListEditor from "../components/TokenListEditor";
import type { ApiSectionConfig } from "../types";

interface ApiKeysSectionProps {
  eyebrow: string;
  title: string;
  description: string;
  config: ApiSectionConfig;
  values: string[];
  onChange: (values: string[]) => void;
}

export default function ApiKeysSection({
  eyebrow,
  title,
  description,
  config,
  values,
  onChange,
}: ApiKeysSectionProps) {
  return (
    <div className="space-y-8">
      <SectionHeader
        eyebrow={eyebrow}
        title={title}
        description={description}
      />

      <div className="grid gap-6 xl:grid-cols-[1.35fr_0.65fr]">
        <TokenListEditor
          providerLabel={config.title}
          values={values}
          minimumRequired={config.minimumRequired}
          optional={config.optional}
          onChange={onChange}
        />
        <HelpRail
          title={config.helpTitle}
          description={config.helpDescription}
          links={config.links}
        />
      </div>
    </div>
  );
}
