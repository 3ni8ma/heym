import type {
  ReleaseEntry,
  ReleaseSection,
  ReleaseTour,
  ReleaseTourSlide,
} from "@/features/release-tour/releaseTour.types";

/**
 * Bump when an already-announced release's tour changes enough to be worth
 * re-showing. Everyone's stored ids keep the old revision, so the tour reopens.
 */
export const TOUR_REVISION = 1;

export function toVersionedReleaseId(releaseId: string, revision: number = TOUR_REVISION): string {
  return `${releaseId}@r${revision}`;
}

function toSlide(section: ReleaseSection): ReleaseTourSlide | null {
  if (!section.tour) return null;

  return {
    id: section.id,
    title: section.title,
    description: section.tour.description,
    useCases: section.tour.useCases,
    tourVisual: section.tour.tourVisual,
    docTarget: section.tour.docTarget,
  };
}

/** Resolves `sectionOrder` into slides, skipping unknown ids and untoured sections. */
export function buildTourSlides(entry: ReleaseEntry): ReleaseTourSlide[] {
  const order = entry.releaseTour?.sectionOrder ?? [];
  const sectionsById = new Map(entry.sections.map((section) => [section.id, section]));

  return order.flatMap((sectionId) => {
    const section = sectionsById.get(sectionId);
    if (!section) return [];

    const slide = toSlide(section);
    return slide ? [slide] : [];
  });
}

/** Returns null for releases with no tour, a disabled tour, or no usable slides. */
export function buildReleaseTour(
  entry: ReleaseEntry,
  revision: number = TOUR_REVISION,
): ReleaseTour | null {
  const meta = entry.releaseTour;
  if (!meta) return null;
  if (meta.tourEnabled === false) return null;

  const slides = buildTourSlides(entry);
  if (slides.length === 0) return null;

  return {
    releaseId: entry.releaseId,
    versionedReleaseId: toVersionedReleaseId(entry.releaseId, revision),
    publishedAt: entry.publishedAt,
    headline: entry.headline,
    label: meta.label,
    introTitle: meta.introTitle,
    introDescription: meta.introDescription,
    introCoverImage: meta.introCoverImage,
    slides,
  };
}

/** Every tourable release, newest `publishedAt` first. */
export function buildReleaseTours(
  entries: ReleaseEntry[],
  revision: number = TOUR_REVISION,
): ReleaseTour[] {
  return entries
    .flatMap((entry) => {
      const tour = buildReleaseTour(entry, revision);
      return tour ? [tour] : [];
    })
    .sort((left, right) => right.publishedAt.getTime() - left.publishedAt.getTime());
}

/**
 * Only the newest eligible release is ever pending. Older unseen releases are
 * skipped on purpose so upgrading across several versions shows one tour.
 */
export function selectPendingReleaseTour(
  tours: ReleaseTour[],
  seenReleaseIds: readonly string[],
): ReleaseTour | null {
  const newest = tours[0];
  if (!newest) return null;

  return seenReleaseIds.includes(newest.versionedReleaseId) ? null : newest;
}
