"use client"

import { useState, useEffect, useRef } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { ChevronLeft, ChevronRight, Calendar, Clock, Home, ImageIcon, MapPin } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"

// Replace this with your actual R2 bucket URL
const R2_BASE_URL = "https://nthgrv.mcgrath.nz/timelapse"

interface WeeklyVideo {
  filename: string
  monday_date: string
  start: string
  end: string
  r2_path: string
}

interface Event {
  title: string
  date: string
  monday_date: string
  description?: string
}

interface Metadata {
  last_updated: string
  total_days: number
  latest_image: {
    date: string
    filename: string
  }
  latest_day: string
  current_week: {
    start: string
    end: string
    monday_date: string
  }
  weekly_videos: WeeklyVideo[]
  date_range: {
    start: string
    end: string
  }
  events?: Event[]
}

type ViewMode = "day" | "week" | "full"

function EventsTimeline({ events, router }: { events: Event[], router: any }) {
  if (!events || events.length === 0) {
    return null
  }

  // Sort events in reverse chronological order (most recent first)
  const sortedEvents = [...events].sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime())

  const formatEventDate = (dateString: string) => {
    return new Date(dateString).toLocaleDateString("en-US", {
      month: "long",
      day: "numeric",
      year: "numeric",
    })
  }

  const navigateToEventWeek = (mondayDate: string) => {
    router.push(`/?view=week&date=${mondayDate}`)
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <MapPin className="h-5 w-5" />
          Construction Milestones
        </CardTitle>
      </CardHeader>
      <CardContent className="p-6">
        <div className="space-y-4">
          {sortedEvents.map((event, index) => (
            <div
              key={index}
              className="flex items-start gap-4 p-4 rounded-lg border hover:bg-slate-50 cursor-pointer transition-colors"
              onClick={() => navigateToEventWeek(event.monday_date)}
            >
              <div className="flex-shrink-0 w-2 h-2 bg-blue-500 rounded-full mt-2"></div>
              <div className="flex-grow">
                <h3 className="font-semibold text-slate-900 mb-1">{event.title}</h3>
                <p className="text-sm text-slate-600 mb-2">{formatEventDate(event.date)}</p>
                {event.description && (
                  <p className="text-sm text-slate-700">{event.description}</p>
                )}
              </div>
              <Button variant="ghost" size="sm" className="flex-shrink-0">
                <Calendar className="h-4 w-4" />
              </Button>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}

export default function TimelapseViewer() {
  const router = useRouter()
  const searchParams = useSearchParams()
  
  const [metadata, setMetadata] = useState<Metadata | null>(null)
  const [currentVideoUrl, setCurrentVideoUrl] = useState<string>("")
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string>("")
  const [isInitialLoad, setIsInitialLoad] = useState(true)
  const videoRef = useRef<HTMLVideoElement>(null)
  
  // Get view mode and selected week from URL params
  const viewParam = searchParams.get("view") as ViewMode | null
  const dateParam = searchParams.get("date")
  
  const viewMode: ViewMode = viewParam || "week"
  const selectedWeek = dateParam || ""

  useEffect(() => {
    fetchMetadata()
  }, [])

  useEffect(() => {
    if (metadata) {
      updateVideoUrl()
      // Auto-play when changing selections (but not on initial load)
      if (!isInitialLoad && videoRef.current) {
        setTimeout(() => {
          videoRef.current?.play().catch(() => {
            // Ignore autoplay errors (browser policy)
          })
        }, 100)
      }
      if (isInitialLoad) {
        setIsInitialLoad(false)
      }
    }
  }, [metadata, viewMode, selectedWeek])

  const fetchMetadata = async () => {
    try {
      setLoading(true)
      setError("")

      const response = await fetch(`${R2_BASE_URL}/metadata.json`, {
        method: "GET",
        headers: {
          Accept: "application/json",
        },
        mode: "cors", // Explicitly set CORS mode
      })

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`)
      }

      const data = await response.json()

      setMetadata(data)
      
      // If viewing week mode without a specific date, redirect to current week
      if (viewMode === "week" && !dateParam) {
        router.push(`/?view=week&date=${data.current_week.monday_date}`)
      }
      
      setError("")
    } catch (err) {
      let errorMessage = "Failed to load timelapse data. "

      if (err instanceof TypeError && err.message.includes("NetworkError")) {
        errorMessage += "Please check your internet connection."
      } else if (err instanceof Error) {
        errorMessage += `Error: ${err.message}`
      }

      setError(errorMessage)
    } finally {
      setLoading(false)
    }
  }

  const updateVideoUrl = () => {
    if (!metadata) return

    const timestamp = Date.now()
    let url = ""
    switch (viewMode) {
      case "day":
        url = `${R2_BASE_URL}/day.mp4?t=${timestamp}`
        break
      case "week":
        const weekDate = selectedWeek || metadata.current_week.monday_date
        if (weekDate === metadata.current_week.monday_date) {
          url = `${R2_BASE_URL}/week.mp4?t=${timestamp}`
        } else {
          url = `${R2_BASE_URL}/weeks/timelapse_week_${weekDate}.mp4?t=${timestamp}`
        }
        break
      case "full":
        url = `${R2_BASE_URL}/full.mp4?t=${timestamp}`
        break
    }
    setCurrentVideoUrl(url)
  }

  const getSelectedWeekData = () => {
    if (!metadata) return null
    const weekDate = selectedWeek || metadata.current_week.monday_date
    return (
      metadata.weekly_videos.find((w) => w.monday_date === weekDate) ||
      (weekDate === metadata.current_week.monday_date
        ? {
            filename: "week.mp4",
            monday_date: metadata.current_week.monday_date,
            start: metadata.current_week.start,
            end: metadata.current_week.end,
            r2_path: "week.mp4",
          }
        : null)
    )
  }

  const navigateWeek = (direction: "prev" | "next") => {
    if (!metadata) return

    const currentWeek = selectedWeek || metadata.current_week.monday_date
    const currentIndex = metadata.weekly_videos.findIndex((w) => w.monday_date === currentWeek)
    let newIndex = currentIndex

    if (direction === "prev" && currentIndex > 0) {
      newIndex = currentIndex - 1
    } else if (direction === "next" && currentIndex < metadata.weekly_videos.length - 1) {
      newIndex = currentIndex + 1
    }

    if (newIndex !== currentIndex) {
      router.push(`/?view=week&date=${metadata.weekly_videos[newIndex].monday_date}`)
    }
  }

  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
    })
  }

  const formatDateRange = (start: string, end: string) => {
    const startDate = new Date(start)
    const endDate = new Date(end)
    return `${startDate.toLocaleDateString("en-US", { month: "short", day: "numeric" })} - ${endDate.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}`
  }

  if (error) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-50 to-slate-100 flex items-center justify-center">
        <Card className="max-w-2xl mx-4">
          <CardContent className="p-6">
            <div className="text-center">
              <div className="text-red-500 mb-4">
                <Home className="h-12 w-12 mx-auto" />
              </div>
              <h2 className="text-xl font-semibold mb-2">Unable to Load Timelapse</h2>
              <p className="text-slate-600 mb-4">{error}</p>
              <Button onClick={fetchMetadata} variant="outline">
                Try Again
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    )
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-50 to-slate-100 flex items-center justify-center">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-slate-600 mx-auto mb-4"></div>
          <p className="text-slate-600">Loading timelapse data...</p>
        </div>
      </div>
    )
  }

  const selectedWeekData = getSelectedWeekData()

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 to-slate-100">
      <div className="container mx-auto px-4 py-8">
        {/* Header */}
        <div className="text-center mb-8">
          <h1 className="text-4xl font-bold text-slate-800 mb-2 flex items-center justify-center gap-3">
            <Home className="h-8 w-8" />
            Northgrove Timelapse
          </h1>
          <p className="text-slate-600 mb-4">
            Day {metadata?.total_days} • Last updated {metadata ? formatDate(metadata.last_updated) : ""}
          </p>
        </div>

        {/* Controls */}
        <Card className="mb-6">
          <CardContent className="p-6">
            <div className="flex flex-col lg:flex-row gap-4 items-center justify-between">
              {/* View Mode Selector */}
              <div className="flex gap-2">
                <Button
                  variant={viewMode === "day" ? "default" : "outline"}
                  onClick={() => router.push("/?view=day")}
                  className="flex items-center gap-2"
                >
                  <Clock className="h-4 w-4" />
                  Today
                </Button>
                <Button
                  variant={viewMode === "week" ? "default" : "outline"}
                  onClick={() => {
                    if (metadata) {
                      router.push(`/?view=week&date=${selectedWeek || metadata.current_week.monday_date}`)
                    }
                  }}
                  className="flex items-center gap-2"
                >
                  <Calendar className="h-4 w-4" />
                  Week
                </Button>
                <Button
                  variant={viewMode === "full" ? "default" : "outline"}
                  onClick={() => router.push("/?view=full")}
                  className="flex items-center gap-2"
                >
                  <Home className="h-4 w-4" />
                  Full
                </Button>
                <div className="h-8 w-px bg-gray-300 mx-2 self-center" />
                <Button
                  onClick={fetchMetadata}
                  variant="outline"
                  size="sm"
                  className="flex items-center gap-2 bg-transparent"
                >
                  <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
                    />
                  </svg>
                </Button>
              </div>

              {/* Week Navigation - Only show for week mode */}
              {viewMode === "week" && metadata && (
                <div className="flex items-center gap-2">
                  <Button
                    variant="outline"
                    size="icon"
                    onClick={() => navigateWeek("prev")}
                    disabled={metadata.weekly_videos.findIndex((w) => w.monday_date === (selectedWeek || metadata.current_week.monday_date)) === 0}
                  >
                    <ChevronLeft className="h-4 w-4" />
                  </Button>

                  <Select 
                    value={selectedWeek || metadata.current_week.monday_date} 
                    onValueChange={(date) => router.push(`/?view=week&date=${date}`)}
                  >
                    <SelectTrigger className="w-48">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {metadata.weekly_videos.map((week) => (
                        <SelectItem key={week.monday_date} value={week.monday_date}>
                          Week of {formatDate(week.start)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>

                  <Button
                    variant="outline"
                    size="icon"
                    onClick={() => navigateWeek("next")}
                    disabled={
                      metadata.weekly_videos.findIndex((w) => w.monday_date === (selectedWeek || metadata.current_week.monday_date)) ===
                      metadata.weekly_videos.length - 1
                    }
                  >
                    <ChevronRight className="h-4 w-4" />
                  </Button>
                </div>
              )}
            </div>
          </CardContent>
        </Card>

        {/* Video Player */}
        <Card className="mb-6">
          <CardContent className="p-0">
            <div className="relative aspect-video bg-black rounded-lg overflow-hidden">
              {currentVideoUrl && (
                <video
                  ref={videoRef}
                  key={currentVideoUrl}
                  controls
                  className="w-full h-full"
                  poster={`${R2_BASE_URL}/latest.jpg?t=${Date.now()}`}
                >
                  <source src={currentVideoUrl} type="video/mp4" />
                  Your browser does not support the video tag.
                </video>
              )}
            </div>
          </CardContent>
        </Card>

        {/* Events Timeline */}
        {metadata?.events && (
          <EventsTimeline events={metadata.events} router={router} />
        )}
      </div>
    </div>
  )
}
