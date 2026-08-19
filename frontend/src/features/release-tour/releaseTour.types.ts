import type { ShowcaseDocTarget } from "@/features/showcase/showcase.types";

export interface ReleaseSectionBlock {
  type: "prose";
  markdown: string;
}

export interface ReleaseSectionTour {
  description: string;
  useCases: string[];
  tourVisual: string;
  docTarget?: ShowcaseDocTarget;
}

export interface ReleaseSection {
  id: string;
  title: string;
  blocks: ReleaseSectionBlock[];
  tour?: ReleaseSectionTour;
}

export interface ReleaseTourMeta {
  label: string;
  introTitle: string;
  introDescription: string;
  introCoverImage?: string;
  tourEnabled?: boolean;
  sectionOrder: string[];
}

export interface ReleaseEntry {
  releaseId: string;
  publishedAt: Date;
  headline: string;
  releaseTour?: ReleaseTourMeta;
  sections: ReleaseSection[];
}

/** One feature screen inside a release tour, already resolved from its section. */
export interface ReleaseTourSlide {
  id: string;
  title: string;
  description: string;
  useCases: string[];
  tourVisual: string;
  docTarget?: ShowcaseDocTarget;
}

/** Runtime shape the popup consumes; built from a `ReleaseEntry` by the mapper. */
export interface ReleaseTour {
  releaseId: string;
  versionedReleaseId: string;
  publishedAt: Date;
  headline: string;
  label: string;
  introTitle: string;
  introDescription: string;
  introCoverImage?: string;
  slides: ReleaseTourSlide[];
}
