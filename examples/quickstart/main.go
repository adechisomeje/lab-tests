package main

import (
	"fmt"
	labtests "github.com/adechisomeje/lab-tests"
)

func main() {
	cat, _ := labtests.Load(labtests.WithProviderRanges("mft-nhs"))

	fmt.Println("== Order set: aesthetic clinic (core) ==")
	set, _ := cat.OrderSet("aesthetic-beauty-clinic", true)
	ids := []string{}
	for i, t := range set {
		if i < 4 {
			fmt.Printf("  %s\n", t.Name)
		}
		ids = append(ids, t.ID)
	}
	fmt.Printf("  ...%d tests total\n\n", len(set))

	fmt.Println("== Draw plan: ammonia + lactate + ferritin ==")
	plan, _ := cat.Draw([]string{"ammonia", "lactate", "ferritin"})
	for _, tube := range plan.Tubes {
		vol := "volume unpublished"
		if tube.VolumeKnown {
			vol = fmt.Sprintf("%.1f mL", tube.TotalVolumeML)
		}
		fmt.Printf("  %d. %-18s %-22s %d test(s), %s\n",
			tube.Position, tube.Type, tube.CapColour, len(tube.Tests), vol)
	}
	fmt.Printf("  source: %.90s...\n", plan.OrderSource)
	for _, w := range plan.Warnings {
		fmt.Printf("  WARN: %.100s...\n", w)
	}

	fmt.Println("\n== Interpret ALT = 62 IU/L ==")
	for _, p := range []labtests.Patient{
		{Sex: labtests.SexMale, Age: labtests.Years(34)},
		{Sex: labtests.SexFemale, Age: labtests.Years(34)},
		{Sex: labtests.SexMale, Age: labtests.Days(10)},
	} {
		r, err := cat.Interpret("alanine-aminotransferase", 62, p)
		if err != nil {
			fmt.Printf("  %s/%v: %v\n", p.Sex, p.Age.Value, err)
			continue
		}
		fmt.Printf("  %-6s age %5.0f %-5s -> %-6s (limit %v %s) [%s]\n",
			p.Sex, p.Age.Value, p.Age.Unit, r.Flag, *r.Stratum.High, r.Units, r.Attribution)
	}

	fmt.Println("\n== Safety: no range source configured ==")
	safe, _ := labtests.Load()
	_, err := safe.Interpret("alanine-aminotransferase", 62,
		labtests.Patient{Sex: labtests.SexMale, Age: labtests.Years(34)})
	fmt.Printf("  %v\n", err)
}
